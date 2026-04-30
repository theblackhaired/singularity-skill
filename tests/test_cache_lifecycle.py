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
            return {"projects": projects if offset == 0 else []}

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

    def test_task_group_partial_rebuild_marks_all_caches_incomplete(self) -> None:
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
            for filename in ("projects.json", "tags.json", "task_groups.json"):
                data = json.loads((refs_dir / filename).read_text(encoding="utf-8"))
                self.assertFalse(data["_meta"]["complete"], filename)

    def test_find_handlers_report_degraded_for_incomplete_cache(self) -> None:
        with temporary_directory() as tmpdir:
            refs_dir = Path(tmpdir) / "references"
            refs_dir.mkdir()
            atomic_write_json(
                refs_dir / "projects.json",
                wrap_cache(
                    "projects",
                    [{"id": "P-1", "title": "Root", "parent": None}],
                    build_cache_meta("/v2/project", complete=False),
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
                    "_meta": build_cache_meta("/v2/task-group", complete=True),
                    "mappings": {"P-1": "TG-1"},
                    "generated": "2026-04-28",
                },
            )

            with mock.patch.object(cli, "REFS_DIR", refs_dir):
                project = cli._find_project_handler(mock.Mock(), None, {"name": "Root", "exact": True})
                tag = cli._find_tag_handler(mock.Mock(), None, {"name": "Urgent", "exact": True})

            self.assertTrue(project["found"])
            self.assertTrue(project["degraded"])
            self.assertEqual(project["reason"], "cache incomplete")
            self.assertTrue(tag["found"])
            self.assertTrue(tag["degraded"])
            self.assertEqual(tag["reason"], "cache incomplete")

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
