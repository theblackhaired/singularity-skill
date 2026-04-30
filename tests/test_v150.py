"""v1.5.0 project description migration and local write tests."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cli
from cache import atomic_write_json, build_cache_meta, wrap_cache


@contextlib.contextmanager
def temporary_directory():
    real_mkdir = tempfile._os.mkdir

    def permissive_mkdir(path, mode=0o777):
        return real_mkdir(path, 0o777)

    with mock.patch("tempfile._os.mkdir", side_effect=permissive_mkdir):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            yield Path(tmpdir)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _projects_doc(projects, *, status="complete"):
    meta = build_cache_meta("/v2/project", total_items=len(projects), complete=True)
    meta["description_migration"] = {
        "version": 1,
        "status": status,
        "completed_at": "2026-04-28T00:00:00+00:00" if status == "complete" else None,
        "source_file": "projects_cache.md",
    }
    return wrap_cache(
        "projects",
        projects,
        meta,
        generated=meta["generated_at"],
        total=len(projects),
        archived=0,
        with_description=sum(1 for p in projects if p.get("description") is not None),
    )


def _write_supporting_caches(refs: Path):
    tag_meta = build_cache_meta("/v2/tag", total_items=0, complete=True)
    tg_meta = build_cache_meta("/v2/task-group", total_items=0, complete=True)
    atomic_write_json(
        refs / "tags.json",
        wrap_cache("tags", [], tag_meta, generated=tag_meta["generated_at"], total=0),
    )
    atomic_write_json(
        refs / "task_groups.json",
        {"_meta": tg_meta, "mappings": {}, "generated": tg_meta["generated_at"]},
    )


def _mock_client(projects=None, tags=None, task_groups=None):
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
            return {"tags": tags if offset == 0 else []}
        if path == "/v2/task-group":
            parent = params.get("parent")
            return {"taskGroups": list(task_groups.get(parent, []))}
        return {}

    client.get.side_effect = get
    return client


def _run_main(root: Path, refs: Path, argv: list[str]) -> tuple[int, str, str]:
    (root / "config.json").write_text(
        json.dumps({
            "base_url": "https://example.invalid",
            "token": "token",
            "read_only": False,
            "cache_ttl_days": None,
        }),
        encoding="utf-8",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = 0
    with mock.patch.object(cli, "ROOT", root), \
         mock.patch.object(cli, "REFS_DIR", refs), \
         mock.patch.object(cli, "SingularityClient", return_value=mock.Mock()), \
         mock.patch("sys.argv", ["cli.py", *argv]), \
         contextlib.redirect_stdout(stdout), \
         contextlib.redirect_stderr(stderr):
        try:
            cli.main()
        except SystemExit as exc:
            code = int(exc.code or 0)
    return code, stdout.getvalue(), stderr.getvalue()


class V150Tests(unittest.TestCase):
    def test_v150_migration_state_detected_via_meta(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": "keep"}], status="pending"),
            )
            (root / "projects_cache.md").write_text("# cache\n", encoding="utf-8")

            code, out, _err = _run_main(
                root, refs, ["--call", json.dumps({"tool": "project_list", "arguments": {}})]
            )

            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["status"], "error")
            self.assertEqual(payload["code"], "MIGRATION_PENDING")
            self.assertEqual(payload["projects_with_description"], 1)

    def test_v150_rebuild_preserves_descriptions(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Old", "description": "local"}]),
            )
            client = _mock_client(
                projects=[{"id": "P-1", "title": "New", "removed": False}],
                tags=[],
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                cli._rebuild_references_handler(client, None, {})

            data = json.loads((refs / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(data["projects"][0]["description"], "local")

    def test_v150_with_description_counter_accurate(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([
                    {"id": "P-1", "title": "One", "description": None},
                    {"id": "P-2", "title": "Two", "description": None},
                ]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "a", "P-2": "b"}}
                )

            self.assertEqual(result["with_description_total"], 2)
            data = json.loads((refs / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(data["with_description"], 2)

    def test_v150_archive_idempotent_with_timestamp(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            source = root / "projects_cache.md"
            source.write_text("# cache\n", encoding="utf-8")
            (root / "projects_cache.md.pre-1.5.0.bak").write_text("old\n", encoding="utf-8")
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}], status="pending"),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "desc"}}
                )

            self.assertEqual(result["migration"]["status"], "complete")
            self.assertFalse(source.exists())
            backups = sorted(p.name for p in root.glob("projects_cache.md.pre-1.5.0.*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertRegex(backups[0], r"2026\d{4}T\d{6}Z\.[0-9a-f]{8}\.bak$")

    def test_v150_already_migrated_other_machine(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}], status="pending"),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._check_description_migration("project_list")

            self.assertIsNone(result)
            data = json.loads((refs / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual(data["_meta"]["description_migration"]["status"], "complete")

    def test_v150_discovery_commands_not_blocked_by_migration(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}], status="pending"),
            )
            (root / "projects_cache.md").write_text("# cache\n", encoding="utf-8")

            list_code, list_out, _ = _run_main(root, refs, ["--list"])
            desc_code, desc_out, _ = _run_main(root, refs, ["--describe", "project_describe"])

            self.assertEqual(list_code, 0)
            self.assertEqual(desc_code, 0)
            self.assertIn("project_describe", list_out)
            self.assertEqual(json.loads(desc_out)["name"], "project_describe")

    def test_v150_describe_invalid_id_returns_structured_error(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"id": "P-missing", "text": "x"}
                )

            self.assertEqual(result["code"], "PROJECT_NOT_FOUND")
            self.assertEqual(result["status"], "error")

    def test_v150_describe_batch_invalid_atomic(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            path = refs / "projects.json"
            atomic_write_json(
                path,
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            before = path.read_bytes()
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "ok", "P-bad": "bad"}}
                )

            self.assertEqual(result["code"], "BATCH_INVALID")
            self.assertEqual(path.read_bytes(), before)

    def test_v150_describe_cas_conflict(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "x"}, "base_sha256": "0" * 64}
                )

            self.assertEqual(result["code"], "CAS_CONFLICT")

    def test_v150_describe_dry_run_no_write(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            path = refs / "projects.json"
            atomic_write_json(
                path,
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            before = _sha256(path)
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "x"}, "dry_run": True}
                )

            self.assertEqual(result["would_add"], 1)
            self.assertEqual(_sha256(path), before)

    def test_v150_cache_ttl_null_no_typeerror(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            _write_supporting_caches(refs)
            cfg = {"base_url": "https://example.invalid", "token": "token", "cache_ttl_days": None}
            with mock.patch.object(cli, "ROOT", root), \
                 mock.patch.object(cli, "REFS_DIR", refs), \
                 mock.patch.object(cli, "_rebuild_references_handler", side_effect=AssertionError("no rebuild")):
                cli._check_and_refresh_cache(cfg)

    def test_v150_describe_empty_string_rejected(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": ""}}
                )
            self.assertEqual(result["code"], "INVALID_DESCRIPTION")

    def test_v150_describe_null_deletes(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": "old"}]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": None}, "force": True}
                )
            self.assertEqual(result["deleted"], 1)
            data = json.loads((refs / "projects.json").read_text(encoding="utf-8"))
            self.assertIsNone(data["projects"][0]["description"])

    def test_v150_local_write_tools_allowed_in_read_only(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            cfg = {
                "base_url": "https://example.invalid",
                "token": "token",
                "read_only": True,
                "cache_ttl_days": None,
            }
            (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            _write_supporting_caches(refs)
            stdout = io.StringIO()
            with mock.patch.object(cli, "ROOT", root), \
                 mock.patch.object(cli, "REFS_DIR", refs), \
                 mock.patch("sys.argv", ["cli.py", "--call", json.dumps({
                     "tool": "project_describe",
                     "arguments": {"batch": {"P-1": "x"}, "dry_run": True},
                 })]), \
                 contextlib.redirect_stdout(stdout):
                cli.main()
            self.assertEqual(json.loads(stdout.getvalue())["status"], "ok")
            self.assertIn("project_describe", cli.LOCAL_WRITE_TOOLS)

    def test_v150_cache_corrupt_structured_error(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            (refs / "projects.json").write_text("{bad", encoding="utf-8")
            _write_supporting_caches(refs)
            cfg = {"base_url": "https://example.invalid", "token": "token"}
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                with self.assertRaises(cli.StructuredError) as ctx:
                    cli._check_and_refresh_cache(cfg)
            self.assertEqual(ctx.exception.payload["code"], "CACHE_CORRUPT")

    def test_v150_description_exists_requires_force(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": "old"}]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "new"}}
                )
            self.assertEqual(result["code"], "DESCRIPTION_EXISTS")

    def test_v150_allow_empty_string(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": ""}, "allow_empty": True}
                )
            self.assertEqual(result["added"], 1)

    def test_v150_batch_and_batch_file_mutually_exclusive(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([{"id": "P-1", "title": "Root", "description": None}]),
            )
            batch_file = root / "batch.json"
            batch_file.write_text(json.dumps({"P-1": "x"}), encoding="utf-8")
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "x"}, "batch_file": str(batch_file)}
                )
            self.assertEqual(result["code"], "BATCH_INVALID")

    def test_v150_duplicate_project_ids_update_all_entries(self):
        with temporary_directory() as root:
            refs = root / "references"
            refs.mkdir()
            atomic_write_json(
                refs / "projects.json",
                _projects_doc([
                    {"id": "P-1", "title": "Root", "description": None},
                    {"id": "P-1", "title": "Root duplicate", "description": None},
                ]),
            )
            with mock.patch.object(cli, "ROOT", root), mock.patch.object(cli, "REFS_DIR", refs):
                result = cli._project_describe_handler(
                    mock.Mock(), None, {"batch": {"P-1": "shared"}}
                )
            self.assertEqual(result["added"], 1)
            data = json.loads((refs / "projects.json").read_text(encoding="utf-8"))
            self.assertEqual([p["description"] for p in data["projects"]], ["shared", "shared"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
