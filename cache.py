"""Atomic reference-cache storage and refresh helpers.

Provides:
  - atomic_write_text(path, content)        — temp+os.replace
  - atomic_write_json(path, obj)            — json+atomic
  - CACHE_SCHEMA_VERSION                    — bump on incompatible meta change
  - build_cache_meta(...)                   — construct CacheMeta dict
  - wrap_cache(items, key, meta)            — top-level dict for cache file
  - read_cache(path)                        — parse and return {meta, items, raw}
  - migrate_legacy_cache(path)              — rename pre-T3 file to *.legacy.json
  - is_cache_complete(path)                 — quick health check
  - parse_html_timestamp_comment(text)      — for projects_cache.md

CacheMeta (TypedDict shape):
  {
    "schema_version":  int,
    "generated_at":    str (ISO 8601 UTC),
    "source_endpoint": str,
    "page_size":       int,
    "pages_fetched":   int,
    "total_items":     int,
    "complete":        bool,
  }
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from client import SingularityClient
from errors import StructuredError, _error_response
from pagination import iterate_pages


CACHE_SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parent
REFS_DIR = ROOT / "references"
MIGRATION_SOURCE_FILE = "projects_cache.md"
MIGRATION_VERSION = 1


def _entrypoint_module():
    return sys.modules.get("cli") or sys.modules.get("__main__")


def _root() -> Path:
    module = _entrypoint_module()
    return Path(getattr(module, "ROOT", ROOT))


def _refs_dir() -> Path:
    module = _entrypoint_module()
    return Path(getattr(module, "REFS_DIR", REFS_DIR))


def _rebuild_handler_for_call():
    module = _entrypoint_module()
    handler = getattr(module, "_rebuild_references_handler", None)
    if handler is not None and handler is not _rebuild_references_handler:
        return handler
    return _rebuild_references_handler


def _client_class_for_call():
    module = _entrypoint_module()
    return getattr(module, "SingularityClient", SingularityClient)


def _iterate_pages_for_call(*args, **kwargs):
    module = _entrypoint_module()
    page_iter = getattr(module, "iterate_pages", None)
    if page_iter is not None and page_iter is not iterate_pages:
        return page_iter(*args, **kwargs)
    return iterate_pages(*args, **kwargs)


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

def atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write `content` to `path` atomically via temp file + os.replace.

    Uses NamedTemporaryFile in the same directory as `path` so os.replace is
    atomic on the same volume. On Windows, os.replace works for closed files.

    Caller is responsible for ensuring no other process holds an open handle
    on `path` during the swap.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # delete=False so the OS doesn't unlink it on close — we need to rename it.
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding=encoding,
        suffix=".tmp",
        prefix=f".{path.name}.",
        dir=str(path.parent),
        delete=False,
        newline="",  # preserve \n exactly as in content
    )
    try:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
    finally:
        tmp.close()

    try:
        os.replace(tmp.name, path)
    except OSError:
        # Clean up the temp file on failure rather than leaking it
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, obj: Any, *, indent: int = 2) -> None:
    """Pretty JSON via atomic_write_text. UTF-8, ensure_ascii=False."""
    text = json.dumps(obj, indent=indent, ensure_ascii=False) + "\n"
    atomic_write_text(Path(path), text)


# ---------------------------------------------------------------------------
# CacheMeta construction & wrapping
# ---------------------------------------------------------------------------

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _project_modification_datetime(value: object) -> datetime | None:
    """Parse the API's epoch-ms or ISO project modification timestamp."""
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if raw.isdigit():
            return datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc)
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _format_sync_watermark(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _max_project_watermark(
    projects: list[dict],
    *,
    fallback: str | None = None,
) -> str | None:
    timestamps = [
        parsed
        for project in projects
        if isinstance(project, dict)
        for parsed in [_project_modification_datetime(project.get("modificatedDate"))]
        if parsed is not None
    ]
    if timestamps:
        return _format_sync_watermark(max(timestamps))
    return fallback


def _overlap_watermark(value: str, seconds: int = 1) -> str:
    parsed = _project_modification_datetime(value)
    if parsed is None:
        return value
    from datetime import timedelta
    return _format_sync_watermark(parsed - timedelta(seconds=seconds))


@contextmanager
def _projects_cache_lock(timeout_seconds: float = 30.0):
    """Cross-process lock for projects.json read/modify/write sequences."""
    lock_path = _refs_dir() / "projects.json.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise StructuredError(
                        "PROJECT_CACHE_LOCK_TIMEOUT",
                        "Timed out waiting for the projects cache lock",
                        file=str(lock_path),
                    )
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def build_cache_meta(
    source_endpoint: str,
    *,
    pages_fetched: int = 1,
    page_size: int = 1000,
    total_items: int = 0,
    complete: bool = True,
) -> dict:
    """Construct a CacheMeta dictionary."""
    return {
        "schema_version": CACHE_SCHEMA_VERSION,
        "generated_at": _now_iso_utc(),
        "source_endpoint": source_endpoint,
        "page_size": int(page_size),
        "pages_fetched": int(pages_fetched),
        "total_items": int(total_items),
        "complete": bool(complete),
    }


def wrap_cache(items_key: str, items: list, meta: dict, **extra: Any) -> dict:
    """Wrap item list with `_meta` block under given key. Extra fields preserved."""
    out: dict = {"_meta": meta, items_key: list(items)}
    for k, v in extra.items():
        if k in out:
            continue  # never overwrite _meta or items_key
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Read / migrate
# ---------------------------------------------------------------------------

def read_cache(path: Path) -> dict | None:
    """Load JSON cache and surface meta separately.

    Returns:
        None if file missing or unparseable
        {"meta": dict|None, "raw": dict, "is_legacy": bool}
    Legacy = no `_meta` block (pre-T3 format).
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    meta = raw.get("_meta") if isinstance(raw.get("_meta"), dict) else None
    return {
        "meta": meta,
        "raw": raw,
        "is_legacy": meta is None,
    }


def is_cache_complete(path: Path) -> bool:
    """True iff file exists, has `_meta`, and `_meta.complete is True`."""
    info = read_cache(Path(path))
    if info is None or info["meta"] is None:
        return False
    return bool(info["meta"].get("complete"))


def migrate_legacy_cache(path: Path) -> Path | None:
    """If `path` is legacy (no `_meta`), rename to `path.with_suffix('.legacy.json')`.

    Returns the legacy path if migration happened, else None.
    Used on the first read after an upgrade; the caller then triggers a rebuild.
    """
    path = Path(path)
    info = read_cache(path)
    if info is None:
        return None
    if not info["is_legacy"]:
        return None
    legacy_path = path.with_suffix(path.suffix + ".legacy")
    # Avoid overwriting an existing legacy backup
    counter = 0
    while legacy_path.exists():
        counter += 1
        legacy_path = path.with_suffix(f"{path.suffix}.legacy{counter}")
    try:
        os.replace(path, legacy_path)
    except OSError:
        return None
    return legacy_path


# ---------------------------------------------------------------------------
# projects_cache.md timestamp helper (used by cli._maybe_auto_refresh_cache)
# ---------------------------------------------------------------------------

_TS_RE = re.compile(r"<!--\s*cache_updated:\s*(\S+?)\s*-->")


def parse_html_timestamp_comment(text: str) -> "datetime | None":
    """Parse `<!-- cache_updated: ISO8601 -->` from arbitrary text head."""
    m = _TS_RE.search(text[:512])
    if not m:
        return None
    try:
        ts = datetime.fromisoformat(m.group(1))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _projects_path() -> Path:
    return _refs_dir() / "projects.json"


def _project_cache_source_path() -> Path:
    return _root() / MIGRATION_SOURCE_FILE


def _count_project_descriptions(projects: list) -> int:
    return sum(1 for p in projects if p.get("description") is not None)


def _default_description_migration(status: str = "pending") -> dict:
    completed_at = _now_iso_utc() if status == "complete" else None
    return {
        "version": MIGRATION_VERSION,
        "status": status,
        "completed_at": completed_at,
        "source_file": MIGRATION_SOURCE_FILE,
    }


def _ensure_description_migration_meta(data: dict, status: str | None = None) -> dict:
    meta = data.setdefault("_meta", {})
    migration = meta.get("description_migration")
    if not isinstance(migration, dict):
        migration = _default_description_migration(status or "pending")
        meta["description_migration"] = migration
    else:
        migration.setdefault("version", MIGRATION_VERSION)
        migration.setdefault("status", status or "pending")
        migration.setdefault("completed_at", None)
        migration.setdefault("source_file", MIGRATION_SOURCE_FILE)
    if status is not None:
        migration["status"] = status
        migration["completed_at"] = _now_iso_utc() if status == "complete" else None
        migration["source_file"] = MIGRATION_SOURCE_FILE
    return migration


def _load_projects_data() -> dict:
    path = _projects_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise StructuredError(
            "CACHE_CORRUPT",
            "references/projects.json is missing",
            file=str(path),
        ) from exc
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise StructuredError(
            "CACHE_CORRUPT",
            "references/projects.json is unreadable or invalid JSON",
            file=str(path),
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


def _set_projects_counters(data: dict) -> None:
    projects = data.get("projects", [])
    data["total"] = len(projects)
    data["archived"] = sum(1 for p in projects if p.get("archived"))
    data["with_description"] = _count_project_descriptions(projects)


def _write_projects_data(data: dict, *, lock_held: bool = False) -> None:
    _set_projects_counters(data)
    if lock_held:
        atomic_write_json(_projects_path(), data)
        return
    with _projects_cache_lock():
        atomic_write_json(_projects_path(), data)


def _project_cache_entry(
    project: dict,
    *,
    existing: dict | None = None,
    description: object = None,
) -> dict:
    existing = existing or {}
    return {
        "id": project["id"],
        "title": project.get("title", existing.get("title", "")),
        "emoji": project.get("emoji", existing.get("emoji")),
        "color": project.get("color", existing.get("color")),
        "parent": project.get("parent", existing.get("parent")),
        "parentOrder": project.get("parentOrder", existing.get("parentOrder")),
        "externalId": project.get("externalId", existing.get("externalId")),
        "modificatedDate": project.get(
            "modificatedDate",
            existing.get("modificatedDate"),
        ),
        "isNotebook": project.get(
            "isNotebook",
            existing.get("isNotebook", False),
        ),
        "archived": project.get(
            "archive",
            project.get("archived", existing.get("archived", False)),
        ),
        "description": description,
    }


def _archive_path_for_project_cache(source: Path) -> Path:
    base = source.with_name(f"{source.name}.pre-1.5.0.bak")
    if not base.exists():
        return base
    sha8 = _sha256_file(source)[:8]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return source.with_name(f"{source.name}.pre-1.5.0.{stamp}.{sha8}.bak")


def _archive_project_cache_if_present() -> dict | None:
    source = _project_cache_source_path()
    if not source.exists():
        return None
    try:
        if not source.read_text(encoding="utf-8").strip():
            raise StructuredError(
                "MIGRATION_SOURCE_EMPTY",
                "projects_cache.md exists but is empty",
                source_path=str(source),
            )
        archive = _archive_path_for_project_cache(source)
        os.replace(source, archive)
        return {"source_path": str(source), "archive_path": str(archive)}
    except StructuredError:
        raise
    except OSError as exc:
        raise StructuredError(
            "ARCHIVE_CONFLICT",
            "could not archive projects_cache.md",
            source_path=str(source),
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


def _migration_pending_response(data: dict) -> dict:
    projects = data.get("projects", [])
    without_description = [
        {"id": p.get("id"), "title": p.get("title", "")}
        for p in projects
        if p.get("description") is None
    ]
    source = _project_cache_source_path()
    archive = source.with_name(f"{source.name}.pre-1.5.0.bak")
    return _error_response(
        "MIGRATION_PENDING",
        "project description migration is pending",
        source_file=MIGRATION_SOURCE_FILE,
        source_path=str(source),
        archive_path=str(archive),
        projects_total=len(projects),
        projects_with_description=_count_project_descriptions(projects),
        projects_without_description=without_description,
        next_action={
            "tool": "project_describe",
            "batch_arg": {
                p.get("id"): p.get("description")
                for p in projects
                if p.get("description") is not None
            },
        },
    )


def _check_description_migration(tool_name: str) -> dict | None:
    if tool_name == "project_describe":
        return None

    data = _load_projects_data()
    migration = _ensure_description_migration_meta(data)
    if migration.get("status") != "pending":
        return None

    source = _project_cache_source_path()
    if source.exists():
        return _migration_pending_response(data)

    _ensure_description_migration_meta(data, "complete")
    _write_projects_data(data)
    return None


def _complete_description_migration_if_pending(data: dict) -> dict | None:
    migration = _ensure_description_migration_meta(data)
    if migration.get("status") == "complete":
        return None
    archive_info = _archive_project_cache_if_present()
    _ensure_description_migration_meta(data, "complete")
    return archive_info


def _rebuild_references_unlocked(client: SingularityClient, _res_key: str,
                                 _args: dict) -> dict:
    """Fetch projects and tags via paginator, merge meta, atomically write caches.

    Uses pagination to avoid silent server-side truncation and writes each cache
    atomically with completeness metadata.
      - All three cache files (projects, tags, task_groups) marked complete=False
        if any list page failed mid-stream.
    """
    refs_dir = _refs_dir()
    refs_dir.mkdir(exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    warnings: list[str] = []
    existing_project_ids: set[str] = set()
    existing_project_descriptions: dict[str, object] = {}
    existing_projects_meta: dict = {}

    projects_file = refs_dir / "projects.json"
    if projects_file.exists():
        try:
            existing_projects_data = json.loads(
                projects_file.read_text(encoding="utf-8")
            )
            existing_projects_meta = (
                existing_projects_data.get("_meta")
                if isinstance(existing_projects_data.get("_meta"), dict)
                else {}
            )
            for project in existing_projects_data.get("projects", []):
                pid = project.get("id")
                if not pid:
                    continue
                existing_project_ids.add(pid)
                existing_project_descriptions[pid] = project.get("description")
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"existing projects cache unreadable: {exc}")

    imported_project_meta_ids = set(
        existing_projects_meta.get("project_meta_imported_ids", [])
        if isinstance(existing_projects_meta.get("project_meta_imported_ids"), list)
        else []
    )

    # Fetch all projects through the paginator.
    proj_pag = _iterate_pages_for_call(
        client, "/v2/project",
        params={"includeRemoved": "false", "includeArchived": "true"},
        wrapper_keys=["projects", "items"],
    )
    projects_raw = [p for p in proj_pag["items"] if not p.get("removed")]
    if proj_pag["partial"]:
        warnings.extend(f"projects: {w}" for w in proj_pag["warnings"])

    # Fetch all tags through the paginator.
    tag_pag = _iterate_pages_for_call(
        client, "/v2/tag",
        params={"includeRemoved": "false"},
        wrapper_keys=["tags", "items"],
    )
    tags_raw = [t for t in tag_pag["items"] if not t.get("removed")]
    if tag_pag["partial"]:
        warnings.extend(f"tags: {w}" for w in tag_pag["warnings"])

    # --- Load meta files (read-only; project_meta is first-import fallback only) ---
    project_meta_path = refs_dir / "project_meta.json"
    project_meta: dict = {}
    if project_meta_path.exists():
        try:
            project_meta = json.loads(
                project_meta_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"project_meta unreadable: {exc}")

    tag_meta_path = refs_dir / "tag_meta.json"
    tag_meta: dict = {}
    if tag_meta_path.exists():
        try:
            tag_meta = json.loads(
                tag_meta_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError) as exc:
            warnings.append(f"tag_meta unreadable: {exc}")

    # --- Build projects.json ---
    projects_out = []
    for p in projects_raw:
        pid = p["id"]
        desc = existing_project_descriptions.get(pid)
        if pid not in existing_project_ids and pid not in imported_project_meta_ids:
            meta_entry = project_meta.get(pid, {})
            if isinstance(meta_entry, dict) and meta_entry.get("description") is not None:
                desc = meta_entry.get("description")
                imported_project_meta_ids.add(pid)
        projects_out.append(_project_cache_entry(p, description=desc))

    projects_out.sort(
        key=lambda x: (x["archived"], (x["title"] or "").lower())
    )

    archived_count = sum(1 for p in projects_out if p["archived"])
    projects_meta = build_cache_meta(
        "/v2/project",
        pages_fetched=proj_pag["fetched_pages"],
        page_size=1000,
        total_items=len(projects_out),
        complete=True,
    )
    existing_migration = (
        existing_projects_meta.get("description_migration")
        if isinstance(existing_projects_meta.get("description_migration"), dict)
        else None
    )
    projects_meta["description_migration"] = existing_migration or _default_description_migration()
    projects_meta["project_meta_imported_ids"] = sorted(imported_project_meta_ids)
    projects_meta["server_checked_at"] = _max_project_watermark(
        projects_raw,
        fallback=projects_meta["generated_at"],
    )
    projects_data = wrap_cache(
        "projects", projects_out, projects_meta,
        # Legacy fields kept for back-compat with consumers that read them directly:
        generated=projects_meta["generated_at"],
        total=len(projects_out),
        archived=archived_count,
        with_description=_count_project_descriptions(projects_out),
    )

    # --- Build tags.json ---
    tags_out = []
    tag_desc_merged = 0
    for t in tags_raw:
        tid = t["id"]
        meta_entry = tag_meta.get(tid, {})
        desc = meta_entry.get("description")
        if desc:
            tag_desc_merged += 1
        tags_out.append({
            "id": tid,
            "title": t.get("title", ""),
            "color": t.get("color"),
            "hotkey": t.get("hotkey"),
            "parent": t.get("parent"),
            "description": desc,
        })

    tags_out.sort(key=lambda x: (x["title"] or "").lower())

    tags_meta = build_cache_meta(
        "/v2/tag",
        pages_fetched=tag_pag["fetched_pages"],
        page_size=1000,
        total_items=len(tags_out),
        complete=True,
    )
    tags_data = wrap_cache(
        "tags", tags_out, tags_meta,
        generated=tags_meta["generated_at"],
        total=len(tags_out),
        with_description=tag_desc_merged,
    )

    # --- Build task_groups.json (project_id -> base_task_group_id mapping) ---
    print(f"[singularity] Fetching task groups for {len(projects_out)} projects...", file=sys.stderr)

    task_groups_mapping: dict = {}
    tg_errors_count = 0
    tg_pages_fetched = 0
    tg_partial = False
    task_group_throttle_ms = max(
        0,
        int(_args.get("task_group_throttle_ms", 750)),
    )

    for idx, p in enumerate(projects_out, 1):
        if idx > 1 and task_group_throttle_ms:
            time.sleep(task_group_throttle_ms / 1000.0)
        project_id = p["id"]

        if idx % 10 == 0 or idx == len(projects_out):
            print(f"[singularity] Progress: {idx}/{len(projects_out)} projects", file=sys.stderr)

        try:
            # Use small page_size — most projects have few task groups; full scan via paginator
            tg_pag = _iterate_pages_for_call(
                client, "/v2/task-group",
                params={"parent": project_id, "includeRemoved": "false"},
                wrapper_keys=["taskGroups", "items"],
                page_size=100,
            )
            tg_pages_fetched += tg_pag["fetched_pages"]
            task_groups = tg_pag["items"]
            if tg_pag["partial"]:
                tg_partial = True
                warnings.extend(
                    f"task_groups[{project_id}]: {w}"
                    for w in tg_pag["warnings"]
                )

            if task_groups:
                # Sort by parentOrder for a deterministic base-section pick;
                # fallback to existing first-element behavior if parentOrder missing.
                tg_sorted = sorted(
                    task_groups,
                    key=lambda g: (g.get("parentOrder") if g.get("parentOrder") is not None else 0),
                )
                base_tg = tg_sorted[0]
                task_groups_mapping[project_id] = base_tg["id"]
        except Exception as e:  # noqa: BLE001 — keep rebuilding even on partial failure
            tg_errors_count += 1
            print(f"[singularity] Warning: Failed to fetch task groups for {project_id}: {e}", file=sys.stderr)
            continue

    projects_complete = not proj_pag["partial"]
    tags_complete = not tag_pag["partial"]
    task_groups_complete = (tg_errors_count == 0) and not tg_partial
    any_partial = bool(not projects_complete or not tags_complete or not task_groups_complete)
    complete = projects_complete and tags_complete and task_groups_complete
    projects_meta["complete"] = projects_complete
    tags_meta["complete"] = tags_complete
    atomic_write_json(refs_dir / "projects.json", projects_data)
    atomic_write_json(refs_dir / "tags.json", tags_data)

    tg_meta = build_cache_meta(
        "/v2/task-group",
        pages_fetched=tg_pages_fetched,
        page_size=100,
        total_items=len(task_groups_mapping),
        complete=task_groups_complete,
    )
    task_groups_data = wrap_cache(
        "mappings", [], tg_meta,
        generated=tg_meta["generated_at"],
        total_projects=len(projects_out),
        mapped=len(task_groups_mapping),
        errors=tg_errors_count,
    )
    # Legacy access pattern: mappings is a dict, not a list — patch shape after wrap.
    task_groups_data["mappings"] = task_groups_mapping
    atomic_write_json(refs_dir / "task_groups.json", task_groups_data)

    print(f"[singularity] Task groups cache built: {len(task_groups_mapping)} mappings", file=sys.stderr)

    return {
        "status": "ok" if not warnings and complete else "degraded",
        "partial": any_partial,
        "generated": today,
        "projects": f"{len(projects_out)} projects ({archived_count} archived, {_count_project_descriptions(projects_out)} with description)",
        "tags": f"{len(tags_out)} tags ({tag_desc_merged} with description)",
        "task_groups": f"{len(task_groups_mapping)} project→task_group mappings ({tg_errors_count} errors)",
        "warnings": warnings,
        "files": [
            "references/projects.json",
            "references/tags.json",
            "references/task_groups.json",
        ],
    }


def _rebuild_references_handler(client: SingularityClient, _res_key: str,
                                args: dict) -> dict:
    with _projects_cache_lock():
        return _rebuild_references_unlocked(client, _res_key, args)


def _fetch_project_pages(
    client: SingularityClient,
    params: dict,
    *,
    page_size: int = 1000,
) -> list[dict]:
    projects: list[dict] = []
    offset = 0
    while True:
        page_params = {
            **params,
            "paginationData": "true",
            "maxCount": page_size,
            "offset": offset,
        }
        body = client.get("/v2/project", params=page_params)
        if not isinstance(body, dict) or not isinstance(body.get("projects"), list):
            raise ValueError("expected response object with a projects array")
        pagination = body.get("pagination")
        if not isinstance(pagination, dict):
            raise ValueError("expected pagination metadata")
        total = pagination.get("total")
        if not isinstance(total, (int, float)) or total < 0:
            raise ValueError("expected non-negative pagination.total")
        page = body["projects"]
        projects.extend(page)
        offset += len(page)
        if offset >= int(total):
            return projects
        if not page:
            raise ValueError("project page ended before pagination.total")
        if offset >= 10_000_000:
            raise ValueError("project pagination safety limit reached")


def _live_project_total(client: SingularityClient) -> int:
    body = client.get(
        "/v2/project",
        params={
            "includeRemoved": "false",
            "includeArchived": "true",
            "paginationData": "true",
            "maxCount": 1,
            "offset": 0,
            "fields": "id",
        },
    )
    pagination = body.get("pagination") if isinstance(body, dict) else None
    total = pagination.get("total") if isinstance(pagination, dict) else None
    if not isinstance(total, (int, float)) or total < 0:
        raise ValueError("expected non-negative live project pagination.total")
    return int(total)


def _sync_projects_cache_from_server_unlocked(client: SingularityClient) -> dict:
    """Validate and incrementally refresh projects.json from the live server.

    A successful cache hit is not proof that the cached project is current.
    Use the last successful server watermark with ``modifiedSince`` on every
    authoritative project lookup, merge all returned deltas, and advance the
    watermark only after the complete delta has been received.

    Validation fails closed: callers must not silently trust the local cache
    when the server check is unavailable or returns an unexpected shape.
    """
    projects_file = _refs_dir() / "projects.json"
    info = read_cache(projects_file)
    if info is None or info["is_legacy"]:
        return {
            "validated": False,
            "refreshed": False,
            "changes": 0,
            "reason": "project cache missing or legacy",
        }

    data = info["raw"]
    meta = info["meta"] or {}
    if meta.get("complete") is not True:
        return {
            "validated": False,
            "refreshed": False,
            "changes": 0,
            "reason": "project cache is incomplete",
        }
    watermark = meta.get("server_checked_at")
    if not isinstance(watermark, str) or not watermark.strip():
        return {
            "validated": False,
            "refreshed": False,
            "changes": 0,
            "reason": "project cache has no server watermark",
        }

    try:
        deltas = _fetch_project_pages(
            client,
            {
                "modifiedSince": _overlap_watermark(watermark),
                "includeRemoved": "true",
                "includeArchived": "true",
            },
        )
    except Exception as exc:
        raise StructuredError(
            "PROJECT_CACHE_VALIDATION_FAILED",
            "Could not validate projects cache against the live server",
            endpoint="/v2/project",
            watermark=watermark,
            cause=f"{type(exc).__name__}: {exc}",
        ) from exc

    projects_by_id = {
        project["id"]: dict(project)
        for project in data.get("projects", [])
        if isinstance(project, dict) and project.get("id")
    }

    changed = 0
    for project in deltas:
        project_id = project.get("id")
        if not project_id:
            continue
        if (
            project.get("removed")
            or project.get("deleteDate")
            or project.get("showInBasket") is False
        ):
            if projects_by_id.pop(project_id, None) is not None:
                changed += 1
            continue

        existing = projects_by_id.get(project_id, {})
        updated = _project_cache_entry(
            project,
            existing=existing,
            description=existing.get("description"),
        )
        if updated != existing:
            changed += 1
        projects_by_id[project_id] = updated

    projects = sorted(
        projects_by_id.values(),
        key=lambda item: (
            bool(item.get("archived")),
            (item.get("title") or "").lower(),
        ),
    )
    try:
        live_total = _live_project_total(client)
        reconciled = len(projects) != live_total
        if reconciled:
            live_projects = _fetch_project_pages(
                client,
                {
                    "includeRemoved": "false",
                    "includeArchived": "true",
                },
            )
            current_by_id = projects_by_id
            projects_by_id = {
                project["id"]: _project_cache_entry(
                    project,
                    existing=current_by_id.get(project["id"], {}),
                    description=current_by_id.get(
                        project["id"],
                        {},
                    ).get("description"),
                )
                for project in live_projects
                if isinstance(project, dict) and project.get("id")
            }
            projects = sorted(
                projects_by_id.values(),
                key=lambda item: (
                    bool(item.get("archived")),
                    (item.get("title") or "").lower(),
                ),
            )
            changed = max(changed, 1)
    except Exception as exc:
        raise StructuredError(
            "PROJECT_CACHE_VALIDATION_FAILED",
            "Could not reconcile projects cache count with the live server",
            endpoint="/v2/project",
            watermark=watermark,
            cause=f"{type(exc).__name__}: {exc}",
        ) from exc

    next_watermark = _max_project_watermark(
        deltas,
        fallback=watermark,
    )
    if changed == 0 and next_watermark == watermark:
        return {
            "validated": True,
            "refreshed": False,
            "changes": 0,
            "watermark": watermark,
        }
    meta["server_checked_at"] = next_watermark
    meta["total_items"] = len(projects)
    data["_meta"] = meta
    data["projects"] = projects
    data["total"] = len(projects)
    data["archived"] = sum(1 for project in projects if project.get("archived"))
    data["with_description"] = _count_project_descriptions(projects)
    atomic_write_json(projects_file, data)

    return {
        "validated": True,
        "refreshed": changed > 0,
        "changes": changed,
        "watermark": meta["server_checked_at"],
        "reconciled": reconciled,
    }


def _sync_projects_cache_from_server(client: SingularityClient) -> dict:
    with _projects_cache_lock():
        return _sync_projects_cache_from_server_unlocked(client)


def _check_and_refresh_cache(cfg: dict) -> None:
    """Auto-refresh references cache if missing or expired.

    Refreshes if:
    - Cache files missing
    - Cache older than cache_ttl_days (from config)
    """
    refs_dir = _refs_dir()

    # Auto-migrate legacy cache data before checking its TTL.
    for fname in ("projects.json", "tags.json", "task_groups.json"):
        fpath = refs_dir / fname
        info = read_cache(fpath)
        if fpath.exists() and info is None:
            raise StructuredError(
                "CACHE_CORRUPT",
                f"{fname} is unreadable or invalid JSON",
                file=str(fpath),
            )
        if info is not None and info["is_legacy"]:
            legacy_path = migrate_legacy_cache(fpath)
            if legacy_path is not None:
                print(f"[singularity] migrated legacy cache: {fname} -> "
                      f"{legacy_path.name}; will rebuild", file=sys.stderr)

    cache_ttl_days = cfg.get("cache_ttl_days", 30)  # Default: 30 days

    projects_file = refs_dir / "projects.json"
    tags_file = refs_dir / "tags.json"
    task_groups_file = refs_dir / "task_groups.json"

    # If any cache missing → rebuild all
    if not projects_file.exists() or not tags_file.exists() or not task_groups_file.exists():
        print("[singularity] Cache missing, rebuilding...", file=sys.stderr)
        _rebuild_handler_for_call()(_client_class_for_call()(cfg["base_url"], cfg["token"]), None, {})
        return

    if cache_ttl_days is None:
        return

    # Check age
    try:
        with projects_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        generated_str = data.get("generated")
        if not generated_str:
            # Old format without timestamp → rebuild
            print("[singularity] Cache has no timestamp, rebuilding...", file=sys.stderr)
            _rebuild_handler_for_call()(_client_class_for_call()(cfg["base_url"], cfg["token"]), None, {})
            return

        generated = datetime.fromisoformat(generated_str)
        # Make aware if naive
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)

        age_days = (datetime.now(timezone.utc) - generated).days

        if age_days >= cache_ttl_days:
            print(f"[singularity] Cache expired ({age_days} days old, TTL={cache_ttl_days}), rebuilding...", file=sys.stderr)
            _rebuild_handler_for_call()(_client_class_for_call()(cfg["base_url"], cfg["token"]), None, {})

    except StructuredError:
        raise
    except (json.JSONDecodeError, OSError, ValueError, TypeError) as e:
        print(f"[singularity] Error checking cache age: {e}, rebuilding...", file=sys.stderr)
        _rebuild_handler_for_call()(_client_class_for_call()(cfg["base_url"], cfg["token"]), None, {})


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "MIGRATION_SOURCE_FILE",
    "MIGRATION_VERSION",
    "ROOT",
    "REFS_DIR",
    "atomic_write_text",
    "atomic_write_json",
    "_projects_cache_lock",
    "build_cache_meta",
    "wrap_cache",
    "read_cache",
    "is_cache_complete",
    "migrate_legacy_cache",
    "parse_html_timestamp_comment",
    "_sha256_file",
    "_projects_path",
    "_project_cache_source_path",
    "_count_project_descriptions",
    "_default_description_migration",
    "_ensure_description_migration_meta",
    "_load_projects_data",
    "_write_projects_data",
    "_archive_path_for_project_cache",
    "_archive_project_cache_if_present",
    "_migration_pending_response",
    "_check_description_migration",
    "_complete_description_migration_if_pending",
    "_rebuild_references_handler",
    "_sync_projects_cache_from_server",
    "_check_and_refresh_cache",
]
