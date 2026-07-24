"""Lifecycle tests for references cache rebuild and legacy migration."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import cli
from cache import atomic_write_json, build_cache_meta, wrap_cache
from errors import StructuredError


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


@contextmanager
def temporary_directory():
    real_mkdir = tempfile._os.mkdir

    def permissive_mkdir(path, mode=0o777):
        return real_mkdir(path, 0o777)

    with mock.patch("tempfile._os.mkdir", side_effect=permissive_mkdir):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            yield tmpdir


def _mock_client(*, projects=None, tags=None, task_groups=None, fail_tag_second_page=False):
    client = mock.Mock(spec=cli.SingularityClient)
    projects = list(projects or [])
    tags = list(tags or [])
    task_groups = dict(task_groups or {})

    def get(path, params=None):
        params = dict(params or {})
        offset = params.get("offset", 0)

        if path == "/v2/project":
            max_count = params.get("maxCount", 1000)
            visible = projects
            if str(params.get("includeRemoved", "false")).lower() == "false":
                visible = [
                    project
                    for project in projects
                    if (
                        not project.get("removed")
                        and not project.get("deleteDate")
                        and project.get("showInBasket") is not False
                    )
                ]
            page = visible[offset:offset + max_count]
            return {
                "projects": page,
                "pagination": {
                    "total": len(visible),
                    "count": len(page),
                    "offset": offset,
                },
            }

        if path == "/v2/tag":
            if fail_tag_second_page and offset >= 1000:
                raise Exception("second page failed")
            return {"tags": tags if offset == 0 else []}

        if path == "/v2/task-group":
            parent = params.get("parent")
            return {"taskGroups": list(task_groups.get(parent, []))}

        return {}

    client.get.side_effect = get
    return client


class CacheLifecycleTests(unittest.TestCase):
    def test_full_rebuild_throttles_between_project_task_group_requests(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            client = _mock_client(
                projects=[
                    {"id": "P-1", "title": "First", "removed": False},
                    {"id": "P-2", "title": "Second", "removed": False},
                ],
                tags=[],
                task_groups={
                    "P-1": [{"id": "TG-1", "parentOrder": 1}],
                    "P-2": [{"id": "TG-2", "parentOrder": 1}],
                },
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir), \
                 mock.patch("cache.time.sleep") as sleep:
                cli._rebuild_references_handler(
                    client,
                    None,
                    {"task_group_throttle_ms": 250},
                )

            sleep.assert_called_once_with(0.25)

    def test_full_rebuild_creates_modern_format(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            client = _mock_client(
                projects=[{"id": "P-1", "title": "Root", "removed": False}],
                tags=[{"id": "TAG-1", "title": "Tag", "removed": False}],
                task_groups={"P-1": [{"id": "TG-1", "parentOrder": 1}]},
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                cli._rebuild_references_handler(client, None, {})

            data = json.loads((refs_dir / "projects.json").read_text(encoding="utf-8"))
            self.assertIn("_meta", data)
            self.assertTrue(data["_meta"]["complete"])

    def test_legacy_cache_auto_migrated(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            (refs_dir / "projects.json").write_text(
                json.dumps({"projects": [{"id": "P-old", "title": "Legacy"}]}),
                encoding="utf-8",
            )
            client = _mock_client(
                projects=[{"id": "P-1", "title": "Root", "removed": False}],
                tags=[],
                task_groups={"P-1": [{"id": "TG-1", "parentOrder": 1}]},
            )
            cfg = {"base_url": "https://example.invalid", "token": "token", "cache_ttl_days": 30}

            with mock.patch.object(cli, "REFS_DIR", refs_dir), \
                 mock.patch.object(cli, "SingularityClient", return_value=client):
                cli._check_and_refresh_cache(cfg)

            migrated = list(refs_dir.glob("projects.json.legacy*"))
            self.assertEqual(len(migrated), 1)
            data = json.loads((refs_dir / "projects.json").read_text(encoding="utf-8"))
            self.assertTrue(data["_meta"]["complete"])

    def test_partial_rebuild_marks_complete_false(self) -> None:
        tags = [
            {"id": f"TAG-{idx}", "title": f"Tag {idx}", "removed": False}
            for idx in range(1000)
        ]
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            client = _mock_client(projects=[], tags=tags, fail_tag_second_page=True)

            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                cli._rebuild_references_handler(client, None, {})

            data = json.loads((refs_dir / "tags.json").read_text(encoding="utf-8"))
            self.assertFalse(data["_meta"]["complete"])

    def test_task_group_partial_rebuild_only_marks_task_group_cache_incomplete(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            project_result = {
                "items": [{"id": "P-1", "title": "Root", "removed": False}],
                "partial": False,
                "fetched_pages": 1,
                "fetched_items": 1,
                "wrapper_key": "projects",
                "warnings": [],
            }
            tag_result = {
                "items": [{"id": "TAG-1", "title": "Tag", "removed": False}],
                "partial": False,
                "fetched_pages": 1,
                "fetched_items": 1,
                "wrapper_key": "tags",
                "warnings": [],
            }
            task_group_result = {
                "items": [{"id": "TG-1", "parentOrder": 1}],
                "partial": True,
                "fetched_pages": 1,
                "fetched_items": 1,
                "wrapper_key": "taskGroups",
                "warnings": ["page_fetch_failed at offset=100"],
            }

            with mock.patch.object(cli, "REFS_DIR", refs_dir), \
                 mock.patch.object(
                     cli,
                     "iterate_pages",
                     side_effect=[project_result, tag_result, task_group_result],
                 ):
                result = cli._rebuild_references_handler(mock.Mock(), None, {})

            self.assertEqual(result["status"], "degraded")
            self.assertTrue(result["partial"])
            projects = json.loads((refs_dir / "projects.json").read_text(encoding="utf-8"))
            tags = json.loads((refs_dir / "tags.json").read_text(encoding="utf-8"))
            task_groups = json.loads((refs_dir / "task_groups.json").read_text(encoding="utf-8"))
            self.assertTrue(projects["_meta"]["complete"])
            self.assertTrue(tags["_meta"]["complete"])
            self.assertFalse(task_groups["_meta"]["complete"])

    def test_find_handlers_report_degraded_for_incomplete_cache(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            atomic_write_json(
                refs_dir / "projects.json",
                wrap_cache(
                    "projects",
                    [{"id": "P-1", "title": "Root", "parent": None}],
                    {
                        **build_cache_meta("/v2/project", complete=True),
                        "server_checked_at": "2026-07-01T00:00:00.000Z",
                    },
                    generated="2026-04-28",
                    total=1,
                    archived=0,
                ),
            )
            atomic_write_json(
                refs_dir / "tags.json",
                wrap_cache(
                    "tags",
                    [{"id": "TAG-1", "title": "Urgent", "parent": None}],
                    build_cache_meta("/v2/tag", complete=False),
                    generated="2026-04-28",
                    total=1,
                ),
            )
            atomic_write_json(
                refs_dir / "task_groups.json",
                {
                    "_meta": build_cache_meta("/v2/task-group", complete=False),
                    "mappings": {"P-1": "TG-1"},
                    "generated": "2026-04-28",
                },
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                project = cli._find_project_handler(
                    _mock_client(projects=[{
                        "id": "P-1",
                        "title": "Root",
                        "parent": None,
                    }]),
                    None,
                    {"name": "Root", "exact": True},
                )
                tag = cli._find_tag_handler(mock.Mock(), None, {"name": "Urgent", "exact": True})

            self.assertTrue(project["found"])
            self.assertTrue(project["degraded"])
            self.assertEqual(project["reason"], "task_groups cache incomplete")
            self.assertTrue(tag["found"])
            self.assertTrue(tag["degraded"])
            self.assertEqual(tag["reason"], "cache incomplete")

    def test_find_project_refreshes_stale_cache_hit_from_server_delta(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            project_meta = build_cache_meta("/v2/project", complete=True)
            project_meta["generated_at"] = "2026-07-01T00:00:00+00:00"
            project_meta["server_checked_at"] = "2026-07-01T00:00:00.000Z"
            atomic_write_json(
                refs_dir / "projects.json",
                wrap_cache(
                    "projects",
                    [{
                        "id": "P-1",
                        "title": "Project Old",
                        "parent": None,
                        "description": "preserve me",
                    }],
                    project_meta,
                    generated=project_meta["generated_at"],
                    total=1,
                    archived=0,
                ),
            )
            atomic_write_json(
                refs_dir / "task_groups.json",
                {
                    "_meta": build_cache_meta("/v2/task-group", complete=True),
                    "mappings": {"P-1": "TG-1"},
                },
            )
            client = _mock_client(
                projects=[{
                    "id": "P-1",
                    "title": "Project New",
                    "parent": "P-root",
                    "parentOrder": 2,
                    "modificatedDate": "1784000000000",
                }],
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                result = cli._find_project_handler(
                    client,
                    None,
                    {"name": "Project", "exact": False},
                )

            self.assertTrue(result["found"])
            self.assertTrue(result["cache_validated"])
            self.assertTrue(result["cache_refreshed"])
            self.assertEqual(result["projects"][0]["title"], "Project New")
            self.assertEqual(result["projects"][0]["description"], "preserve me")
            self.assertEqual(result["projects"][0]["parent"], "P-root")

    def test_find_project_fails_closed_when_server_validation_fails(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            atomic_write_json(
                refs_dir / "projects.json",
                wrap_cache(
                    "projects",
                    [{"id": "P-1", "title": "Stale Project"}],
                    {
                        **build_cache_meta("/v2/project", complete=True),
                        "server_checked_at": "2026-07-01T00:00:00.000Z",
                    },
                ),
            )
            client = mock.Mock(spec=cli.SingularityClient)
            client.get.side_effect = RuntimeError("server unavailable")

            with mock.patch.object(cli, "REFS_DIR", refs_dir), \
                 self.assertRaises(StructuredError) as raised:
                cli._find_project_handler(
                    client,
                    None,
                    {"name": "Stale Project", "exact": True},
                )

            self.assertEqual(
                raised.exception.payload["code"],
                "PROJECT_CACHE_VALIDATION_FAILED",
            )

    def test_project_delta_paginates_using_server_total_not_requested_page_size(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            meta = build_cache_meta("/v2/project", complete=True)
            meta["server_checked_at"] = "2026-07-01T00:00:00.000Z"
            atomic_write_json(
                refs_dir / "projects.json",
                wrap_cache("projects", [], meta),
            )
            atomic_write_json(
                refs_dir / "task_groups.json",
                {
                    "_meta": build_cache_meta("/v2/task-group", complete=False),
                    "mappings": {},
                },
            )
            deltas = [
                {
                    "id": "P-1",
                    "title": "One",
                    "modificatedDate": "1784000000000",
                },
                {
                    "id": "P-2",
                    "title": "Two",
                    "modificatedDate": "1784000001000",
                },
            ]
            client = mock.Mock(spec=cli.SingularityClient)

            def capped_get(path, params=None):
                self.assertEqual(path, "/v2/project")
                params = dict(params or {})
                if "modifiedSince" in params:
                    self.assertRegex(
                        params["modifiedSince"],
                        r"^\d{4}-\d{2}-\d{2}T",
                    )
                offset = int(params.get("offset", 0))
                cap = 1 if "modifiedSince" in params else int(
                    params.get("maxCount", 1)
                )
                page = deltas[offset:offset + cap]
                return {
                    "projects": page,
                    "pagination": {
                        "total": len(deltas),
                        "count": len(page),
                        "offset": offset,
                    },
                }

            client.get.side_effect = capped_get
            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                result = cli._find_project_handler(
                    client,
                    None,
                    {"name": "o", "exact": False},
                )

            self.assertEqual(result["count"], 2)
            self.assertEqual(client.get.call_count, 3)

    def test_new_project_refreshes_its_missing_task_group_mapping(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            meta = build_cache_meta("/v2/project", complete=True)
            meta["server_checked_at"] = "2026-07-01T00:00:00.000Z"
            atomic_write_json(
                refs_dir / "projects.json",
                wrap_cache("projects", [], meta),
            )
            atomic_write_json(
                refs_dir / "task_groups.json",
                {
                    "_meta": build_cache_meta("/v2/task-group", complete=True),
                    "mappings": {},
                },
            )
            client = _mock_client(
                projects=[{
                    "id": "P-NEW",
                    "title": "New Project",
                    "modificatedDate": "1784000000000",
                }],
                task_groups={
                    "P-NEW": [{
                        "id": "Q-NEW",
                        "title": "Без секции",
                        "parent": "P-NEW",
                        "parentOrder": 1,
                    }],
                },
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                result = cli._find_project_handler(
                    client,
                    None,
                    {"name": "New Project", "exact": True},
                )

            self.assertTrue(result["found"])
            self.assertEqual(result["projects"][0]["task_group_id"], "Q-NEW")
            self.assertNotIn("degraded", result)

    def test_project_delta_removes_deleted_project(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            meta = build_cache_meta("/v2/project", complete=True)
            meta["server_checked_at"] = "2026-07-01T00:00:00.000Z"
            atomic_write_json(
                refs_dir / "projects.json",
                wrap_cache(
                    "projects",
                    [{"id": "P-1", "title": "Deleted Project"}],
                    meta,
                ),
            )
            atomic_write_json(
                refs_dir / "task_groups.json",
                {
                    "_meta": build_cache_meta("/v2/task-group", complete=True),
                    "mappings": {"P-1": "Q-1"},
                },
            )
            client = _mock_client(
                projects=[{
                    "id": "P-1",
                    "title": "Deleted Project",
                    "deleteDate": None,
                    "showInBasket": False,
                    "modificatedDate": "1784000000000",
                }],
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir), \
                 mock.patch.object(cli, "_rebuild_references_handler") as rebuild:
                result = cli._find_project_handler(
                    client,
                    None,
                    {"name": "Deleted Project", "exact": True},
                )

            self.assertFalse(result["found"])
            self.assertTrue(result["cache_refreshed"])
            rebuild.assert_called_once()

    def test_atomic_write_no_partial_on_interrupt(self) -> None:
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            original = {"status": "original"}
            path.write_text(json.dumps(original), encoding="utf-8")

            with mock.patch("os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    atomic_write_json(path, {"status": "replacement"})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_config_md5_unchanged_after_full_rebuild(self) -> None:
        cfg_path = cli.ROOT / "config.json"
        if not cfg_path.exists():
            self.skipTest("config.json missing")
        before = _md5(cfg_path)

        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            client = _mock_client(
                projects=[{"id": "P-1", "title": "Root", "removed": False}],
                tags=[{"id": "TAG-1", "title": "Tag", "removed": False}],
                task_groups={"P-1": [{"id": "TG-1", "parentOrder": 1}]},
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                cli._rebuild_references_handler(client, None, {})

        self.assertEqual(before, _md5(cfg_path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
