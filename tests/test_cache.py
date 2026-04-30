"""Tests for cache.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cache import (
    CACHE_SCHEMA_VERSION,
    atomic_write_json,
    atomic_write_text,
    build_cache_meta,
    is_cache_complete,
    migrate_legacy_cache,
    parse_html_timestamp_comment,
    read_cache,
    wrap_cache,
)


@contextmanager
def temporary_directory():
    real_mkdir = tempfile._os.mkdir

    def permissive_mkdir(path, mode=0o777):
        return real_mkdir(path, 0o777)

    with patch("tempfile._os.mkdir", side_effect=permissive_mkdir):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmpdir:
            yield tmpdir


class CacheTests(unittest.TestCase):
    def test_atomic_write_text_creates_file(self) -> None:
        """write to new path, verify file exists with correct content."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.txt"

            atomic_write_text(path, "hello\nworld")

            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "hello\nworld")

    def test_atomic_write_text_overwrites(self) -> None:
        """existing file is overwritten atomically."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.txt"
            path.write_text("old", encoding="utf-8")

            atomic_write_text(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "new")

    def test_atomic_write_text_creates_parent_dir(self) -> None:
        """path.parent does not exist, so atomic_write_text creates dirs and writes."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "nested" / "dir" / "cache.txt"

            atomic_write_text(path, "content")

            self.assertTrue(path.parent.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "content")

    def test_atomic_write_text_no_partial_on_interrupt(self) -> None:
        """os.replace failure propagates, keeps original content, and removes temp files."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.txt"
            path.write_text("original", encoding="utf-8")

            with patch("os.replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    atomic_write_text(path, "replacement")

            self.assertEqual(path.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(Path(tmpdir).glob("*.tmp")), [])

    def test_atomic_write_json_pretty(self) -> None:
        """obj={'a':1,'b':[2,3]} writes indent=2 JSON with trailing newline."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            obj = {"a": 1, "b": [2, 3]}

            atomic_write_json(path, obj)

            text = path.read_text(encoding="utf-8")
            self.assertEqual(text, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
            self.assertEqual(json.loads(text), obj)

    def test_atomic_write_json_unicode(self) -> None:
        """obj={'title': 'Привет'} reads back with same unicode and ensure_ascii=False."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            greeting = "\u041f\u0440\u0438\u0432\u0435\u0442"
            obj = {"title": greeting}

            atomic_write_json(path, obj)

            text = path.read_text(encoding="utf-8")
            self.assertIn(greeting, text)
            self.assertNotIn("\\u041f", text)
            self.assertEqual(json.loads(text), obj)

    def test_build_cache_meta_defaults(self) -> None:
        """build_cache_meta('/v2/project') returns documented defaults and UTC ISO time."""
        meta = build_cache_meta("/v2/project")

        self.assertEqual(meta["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertTrue(meta["complete"])
        self.assertEqual(meta["pages_fetched"], 1)
        self.assertEqual(meta["page_size"], 1000)
        self.assertEqual(meta["total_items"], 0)
        self.assertEqual(meta["source_endpoint"], "/v2/project")
        self.assertTrue(meta["generated_at"].endswith("+00:00"))
        parsed = datetime.fromisoformat(meta["generated_at"])
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_wrap_cache_basic(self) -> None:
        """wrap_cache('projects', [{'id':'P-1'}], meta) keeps _meta and projects keys."""
        meta = build_cache_meta("/v2/project")

        wrapped = wrap_cache("projects", [{"id": "P-1"}], meta)

        self.assertEqual(set(wrapped.keys()), {"_meta", "projects"})
        self.assertIs(wrapped["_meta"], meta)
        self.assertEqual(wrapped["projects"], [{"id": "P-1"}])

    def test_wrap_cache_extra_fields_preserved(self) -> None:
        """wrap_cache('tags', [], meta, total=5, archived=2) keeps extras at top level."""
        meta = build_cache_meta("/v2/tag")

        wrapped = wrap_cache("tags", [], meta, total=5, archived=2)

        self.assertEqual(wrapped["total"], 5)
        self.assertEqual(wrapped["archived"], 2)
        self.assertEqual(wrapped["tags"], [])

    def test_wrap_cache_extra_cant_overwrite_meta_or_items(self) -> None:
        """extra args named _meta or items key do not overwrite protected fields."""
        meta = build_cache_meta("/v2/project")

        wrapped = wrap_cache("projects", [1], meta, _meta="evil", projects="evil")

        self.assertIs(wrapped["_meta"], meta)
        self.assertEqual(wrapped["projects"], [1])

    def test_read_cache_missing_returns_none(self) -> None:
        """read_cache('/nonexistent/path.json') returns None."""
        with temporary_directory() as tmpdir:
            self.assertIsNone(read_cache(Path(tmpdir) / "missing.json"))

    def test_read_cache_invalid_json_returns_none(self) -> None:
        """file containing 'not json' returns None."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            path.write_text("not json", encoding="utf-8")

            self.assertIsNone(read_cache(path))

    def test_read_cache_legacy_no_meta(self) -> None:
        """file {'projects':[]} without '_meta' returns is_legacy=True and meta=None."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            raw = {"projects": []}
            path.write_text(json.dumps(raw), encoding="utf-8")

            result = read_cache(path)

            self.assertIsNotNone(result)
            self.assertTrue(result["is_legacy"])
            self.assertIsNone(result["meta"])
            self.assertEqual(result["raw"], raw)

    def test_read_cache_modern_with_meta(self) -> None:
        """file with '_meta' returns is_legacy=False and current schema metadata."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            meta = build_cache_meta("/v2/project")
            raw = wrap_cache("projects", [], meta)
            path.write_text(json.dumps(raw), encoding="utf-8")

            result = read_cache(path)

            self.assertIsNotNone(result)
            self.assertFalse(result["is_legacy"])
            self.assertIsNotNone(result["meta"])
            self.assertEqual(result["meta"]["schema_version"], CACHE_SCHEMA_VERSION)
            self.assertEqual(result["raw"], raw)

    def test_is_cache_complete(self) -> None:
        """missing, legacy, and incomplete caches are false; complete metadata is true."""
        with temporary_directory() as tmpdir:
            root = Path(tmpdir)
            missing = root / "missing.json"
            legacy = root / "legacy.json"
            incomplete = root / "incomplete.json"
            complete = root / "complete.json"

            legacy.write_text(json.dumps({"projects": []}), encoding="utf-8")
            incomplete.write_text(
                json.dumps(wrap_cache("projects", [], build_cache_meta("/v2/project", complete=False))),
                encoding="utf-8",
            )
            complete.write_text(
                json.dumps(wrap_cache("projects", [], build_cache_meta("/v2/project", complete=True))),
                encoding="utf-8",
            )

            self.assertFalse(is_cache_complete(missing))
            self.assertFalse(is_cache_complete(legacy))
            self.assertFalse(is_cache_complete(incomplete))
            self.assertTrue(is_cache_complete(complete))

    def test_migrate_legacy_cache_renames(self) -> None:
        """legacy file is renamed, preserving content; repeating after rename returns None."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            raw = {"projects": []}
            path.write_text(json.dumps(raw), encoding="utf-8")

            legacy_path = migrate_legacy_cache(path)

            self.assertEqual(legacy_path, path.with_suffix(path.suffix + ".legacy"))
            self.assertFalse(path.exists())
            self.assertTrue(legacy_path.exists())
            self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8")), raw)
            self.assertIsNone(migrate_legacy_cache(path))

    def test_migrate_legacy_cache_modern_returns_none(self) -> None:
        """modern file with _meta is not renamed and migration returns None."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            raw = wrap_cache("projects", [], build_cache_meta("/v2/project"))
            path.write_text(json.dumps(raw), encoding="utf-8")

            self.assertIsNone(migrate_legacy_cache(path))
            self.assertTrue(path.exists())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), raw)

    def test_migrate_legacy_avoid_overwriting_existing_legacy(self) -> None:
        """existing legacy backup is not overwritten; migration chooses a numbered path."""
        with temporary_directory() as tmpdir:
            path = Path(tmpdir) / "cache.json"
            existing_legacy = path.with_suffix(path.suffix + ".legacy")
            raw = {"projects": []}
            existing_raw = {"old": True}
            path.write_text(json.dumps(raw), encoding="utf-8")
            existing_legacy.write_text(json.dumps(existing_raw), encoding="utf-8")

            migrated = migrate_legacy_cache(path)

            self.assertEqual(migrated, path.with_suffix(f"{path.suffix}.legacy1"))
            self.assertEqual(json.loads(existing_legacy.read_text(encoding="utf-8")), existing_raw)
            self.assertEqual(json.loads(migrated.read_text(encoding="utf-8")), raw)
            self.assertFalse(path.exists())

    def test_parse_html_timestamp_basic(self) -> None:
        """basic cache_updated comment without timezone is parsed as UTC-aware."""
        text = "<!-- cache_updated: 2026-04-26T12:00:00 -->"

        parsed = parse_html_timestamp_comment(text)

        self.assertEqual(parsed, datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc))

    def test_parse_html_timestamp_with_tz(self) -> None:
        """cache_updated comment with +03:00 preserves that timezone offset."""
        text = "<!-- cache_updated: 2026-04-26T12:00:00+03:00 -->"

        parsed = parse_html_timestamp_comment(text)

        self.assertEqual(parsed, datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone(timedelta(hours=3))))

    def test_parse_html_timestamp_missing(self) -> None:
        """text without a cache_updated comment returns None."""
        self.assertIsNone(parse_html_timestamp_comment("no comment here"))

    def test_parse_html_timestamp_invalid(self) -> None:
        """invalid cache_updated timestamp value returns None."""
        self.assertIsNone(parse_html_timestamp_comment("<!-- cache_updated: not-a-date -->"))


if __name__ == "__main__":
    unittest.main()
