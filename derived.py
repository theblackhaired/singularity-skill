"""Derived and computed handlers for singularity skill."""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import quote

from cache import atomic_write_json, read_cache, _sync_projects_cache_from_server
from client import SingularityClient
from config import ROOT
from note_resolver import resolve_note
from pagination import iterate_pages

REFS_DIR = ROOT / "references"

# Wired by cli.py after rebuild handler definition to avoid a circular import
# while preserving cache-miss rebuild behavior during Stage 2 extraction.
_rebuild_references_handler = None


def _task_move_handler(client: SingularityClient, _res_key: str,
                       args: dict) -> dict:
    """Move a task and resolve its target project section atomically."""
    task_id = str(args.get("id") or "").strip()
    project_id = str(args.get("project_id") or "").strip()
    section_id = str(args.get("section_id") or "").strip()
    section_title = str(args.get("section") or "").strip()

    if not task_id.startswith("T-"):
        raise ValueError("id must be a task ID in T-uuid format")
    if not project_id.startswith("P-"):
        raise ValueError("project_id must be a project ID in P-uuid format")
    if section_id and section_title:
        raise ValueError("section_id and section are mutually exclusive")
    if section_id and not section_id.startswith("Q-"):
        raise ValueError("section_id must be a task group ID in Q-uuid format")

    if section_id:
        target_group = client.get(
            f"/v2/task-group/{quote(section_id, safe='')}"
        )
        if (
            not isinstance(target_group, dict)
            or target_group.get("id") != section_id
            or target_group.get("parent") != project_id
            or target_group.get("removed")
        ):
            raise ValueError(
                "section_id does not identify a live section of the "
                "target project"
            )
    else:
        pag = iterate_pages(
            client,
            "/v2/task-group",
            params={"parent": project_id, "includeRemoved": "false"},
            wrapper_keys=["taskGroups", "items"],
        )
        if pag["partial"]:
            detail = "; ".join(pag["warnings"])
            raise ValueError(
                "target project sections could not be read completely; "
                "specify section_id explicitly or grant task-group read scope"
                + (f": {detail}" if detail else "")
            )

        groups = [
            group for group in pag["items"]
            if (
                isinstance(group, dict)
                and not group.get("removed")
                and group.get("parent") == project_id
                and str(group.get("id") or "").startswith("Q-")
            )
        ]

        if section_title:
            wanted = section_title.casefold()
            matches = [
                group for group in groups
                if str(group.get("title") or "").strip().casefold() == wanted
            ]
        elif len(groups) == 1:
            matches = groups
        else:
            matches = []

        if len(matches) != 1:
            available = [
                {"id": group.get("id"), "title": group.get("title", "")}
                for group in sorted(
                    groups,
                    key=lambda group: (
                        group.get("parentOrder")
                        if group.get("parentOrder") is not None else 0,
                        str(group.get("id") or ""),
                    ),
                )
            ]
            if len(matches) > 1:
                reason = "section is ambiguous"
            elif not section_title and len(groups) > 1:
                reason = (
                    "target project has multiple sections; "
                    "specify section or section_id"
                )
            else:
                reason = "section was not found in the target project"
            raise ValueError(f"{reason}; available sections: {available}")

        target_group = matches[0]
    target_group_id = target_group["id"]
    client.patch(
        f"/v2/task/{quote(task_id, safe='')}",
        {"projectId": project_id, "group": target_group_id},
    )
    task = client.get(f"/v2/task/{quote(task_id, safe='')}")
    if (
        task.get("projectId") != project_id
        or task.get("group") != target_group_id
    ):
        raise ValueError(
            "task move verification failed: API returned "
            f"projectId={task.get('projectId')!r}, group={task.get('group')!r}"
        )

    return {
        "status": "ok",
        "task": task,
        "project_id": project_id,
        "section": {
            "id": target_group_id,
            "title": target_group.get("title", ""),
            "verified_for_project": True,
        },
        "warnings": [],
    }


def _load_indexed_projects():
    """Load projects.json and build search indexes.

    Returns dict with:
      - 'raw': list of all projects
      - 'by_id': {project_id: project}
      - 'by_title_lower': {title.lower(): project}
      - 'by_parent': {parent_id: [child_projects]}

    Returns None if file doesn't exist.
    """
    projects_file = REFS_DIR / "projects.json"
    if not projects_file.exists():
        return None

    with projects_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else None
    cache_incomplete = bool(meta is not None and meta.get("complete") is False)

    # Build indexes
    by_id = {}
    by_title_lower = {}
    by_parent = {}

    skipped = 0
    for p in projects:
        # A single corrupt entry must not crash the whole index.
        pid = p.get("id")
        if not pid:
            skipped += 1
            continue
        title_lower = (p.get("title") or "").lower()
        parent = p.get("parent")

        by_id[pid] = p
        by_title_lower[title_lower] = p

        if parent:
            if parent not in by_parent:
                by_parent[parent] = []
            by_parent[parent].append(p)

    if skipped:
        print(f"[singularity] _load_indexed_projects: skipped {skipped} "
              f"entries without 'id'", file=sys.stderr)

    return {
        "raw": projects,
        "by_id": by_id,
        "by_title_lower": by_title_lower,
        "by_parent": by_parent,
        "metadata": {
            "generated": data.get("generated"),
            "total": data.get("total", len(projects)),
            "archived": data.get("archived", 0),
            # Strategy (b): serve partial cache data, but make degradation explicit
            # so callers never treat _meta.complete=False as a healthy cache.
            "complete": False if cache_incomplete else True,
            "degraded": cache_incomplete,
            "reason": "cache incomplete" if cache_incomplete else None,
        }
    }


def _load_indexed_tags():
    """Load tags.json and build search indexes.

    Returns dict with:
      - 'raw': list of all tags
      - 'by_id': {tag_id: tag}
      - 'by_title_lower': {title.lower(): tag}
      - 'by_parent': {parent_id: [child_tags]}

    Returns None if file doesn't exist.
    """
    tags_file = REFS_DIR / "tags.json"
    if not tags_file.exists():
        return None

    with tags_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    tags = data.get("tags", [])
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else None
    cache_incomplete = bool(meta is not None and meta.get("complete") is False)

    # Build indexes
    by_id = {}
    by_title_lower = {}
    by_parent = {}

    for t in tags:
        tid = t["id"]
        title_lower = t.get("title", "").lower()
        parent = t.get("parent")

        by_id[tid] = t
        by_title_lower[title_lower] = t

        if parent:
            if parent not in by_parent:
                by_parent[parent] = []
            by_parent[parent].append(t)

    return {
        "raw": tags,
        "by_id": by_id,
        "by_title_lower": by_title_lower,
        "by_parent": by_parent,
        "metadata": {
            "generated": data.get("generated"),
            "total": data.get("total", len(tags)),
            # Strategy (b): serve partial cache data, but make degradation explicit
            # so callers never treat _meta.complete=False as a healthy cache.
            "complete": False if cache_incomplete else True,
            "degraded": cache_incomplete,
            "reason": "cache incomplete" if cache_incomplete else None,
        }
    }


def _generate_meta_template_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    """Generate meta template file with _title for user-friendly editing."""
    meta_type = args.get("type")
    if meta_type not in ("projects", "tags"):
        raise ValueError("type must be 'projects' or 'tags'")

    overwrite = args.get("overwrite", False)

    # Paths
    cache_file = REFS_DIR / f"{meta_type}.json"
    meta_file = REFS_DIR / f"{meta_type[:-1]}_meta.json"  # project_meta.json or tag_meta.json

    # Check if cache exists
    if not cache_file.exists():
        raise FileNotFoundError(
            f"{cache_file} not found. Run rebuild_references first."
        )

    # Check if meta file exists
    if meta_file.exists() and not overwrite:
        raise FileExistsError(
            f"{meta_file} already exists. Use overwrite=true to replace."
        )

    # Load cache
    with cache_file.open("r", encoding="utf-8") as f:
        cache_data = json.load(f)

    cache_meta = cache_data.get("_meta") if isinstance(cache_data.get("_meta"), dict) else None
    cache_incomplete = bool(cache_meta is not None and cache_meta.get("complete") is False)
    items = cache_data.get(meta_type, [])

    # Load existing meta (if exists) to preserve descriptions
    existing_meta = {}
    if meta_file.exists():
        try:
            with meta_file.open("r", encoding="utf-8") as f:
                existing_meta = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[singularity] meta file unreadable, ignoring: {exc}", file=sys.stderr)

    # Build template
    template = {}
    for item in items:
        item_id = item["id"]
        existing = existing_meta.get(item_id, {})

        template[item_id] = {
            "_title": item.get("title", ""),
            "description": existing.get("description", "")
        }

    # Write atomically and use O_EXCL to avoid overwrite races.
    REFS_DIR.mkdir(exist_ok=True)
    existed_before = meta_file.exists()  # capture BEFORE write — review fix
    if overwrite:
        atomic_write_json(meta_file, template)
    else:
        # O_EXCL guards against TOCTOU: two concurrent runs both passing exists()-check
        # would otherwise race and clobber each other.
        try:
            fd = os.open(str(meta_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            raise FileExistsError(
                f"{meta_file} already exists. Use overwrite=true to replace."
            )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=2, ensure_ascii=False)
                f.write("\n")
        except (OSError, TypeError, ValueError):
            # Don't leak partial file on error (TypeError/ValueError from json.dump)
            try:
                os.unlink(str(meta_file))
            except OSError:
                pass
            raise

    result = {
        "status": "success",
        "file": str(meta_file),
        "items": len(template),
        "overwritten": existed_before and overwrite,
    }
    if cache_incomplete:
        result["degraded"] = True
        result["reason"] = "cache incomplete"
    return result


def _refresh_task_group_mappings(
    client: SingularityClient,
    project_ids: list[str],
) -> dict:
    """Refresh missing base task-group mappings for newly discovered projects."""
    path = REFS_DIR / "task_groups.json"
    info = read_cache(path)
    data = info["raw"] if info is not None else {
        "_meta": {"complete": True},
        "mappings": {},
    }
    mappings = data.setdefault("mappings", {})
    warnings: list[str] = []
    changed = False

    for project_id in sorted(set(project_ids)):
        pag = iterate_pages(
            client,
            "/v2/task-group",
            params={"parent": project_id, "includeRemoved": "false"},
            wrapper_keys=["taskGroups", "items"],
            page_size=100,
        )
        if pag["partial"]:
            warnings.extend(
                f"{project_id}: {warning}"
                for warning in pag["warnings"]
            )
            continue
        groups = [
            group
            for group in pag["items"]
            if (
                isinstance(group, dict)
                and str(group.get("id") or "").startswith("Q-")
                and group.get("parent") == project_id
                and not group.get("removed")
            )
        ]
        if not groups:
            warnings.append(f"{project_id}: no live task group")
            continue
        base_group = min(
            groups,
            key=lambda group: (
                group.get("parentOrder")
                if group.get("parentOrder") is not None else 0,
                group["id"],
            ),
        )
        if mappings.get(project_id) != base_group["id"]:
            mappings[project_id] = base_group["id"]
            changed = True

    meta = data.setdefault("_meta", {})
    if warnings:
        meta["complete"] = False
    meta["total_items"] = len(mappings)
    if changed or warnings:
        atomic_write_json(path, data)
    return {
        "changed": changed,
        "warnings": warnings,
    }


def _find_project_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    """Find project by name after validating the cache against the server.

    Returns projects with task_group_id field added from task_groups.json cache.
    """
    name = args.get("name", "").lower()
    exact = args.get("exact", False)

    if not name:
        raise ValueError("name is required")

    cache_sync = _sync_projects_cache_from_server(client)
    cache_rebuilt_before_search = False
    if not cache_sync["validated"]:
        print(
            "[singularity] Project cache cannot be server-validated; rebuilding...",
            file=sys.stderr,
        )
        _rebuild_references_handler(client, None, {})
        cache_rebuilt_before_search = True
        cache_sync = _sync_projects_cache_from_server(client)
        if not cache_sync["validated"]:
            raise RuntimeError(
                "project cache remained unverifiable after rebuild: "
                f"{cache_sync.get('reason', 'unknown reason')}"
            )

    def search_project():
        """Search in indexed cache and enrich with task_group_id."""
        indexed = _load_indexed_projects()
        if not indexed:
            return None

        # Load task_groups mapping
        task_groups_file = REFS_DIR / "task_groups.json"
        task_groups_mapping = {}
        tg_info = None
        degraded_reasons = []
        if indexed["metadata"].get("degraded"):
            degraded_reasons.append("project cache incomplete")
        if task_groups_file.exists():
            try:
                tg_info = read_cache(task_groups_file)
                tg_data = tg_info["raw"] if tg_info is not None else {}
                task_groups_mapping = tg_data.get("mappings", {})
                tg_meta = tg_info["meta"] if tg_info is not None else None
                if tg_meta is not None and tg_meta.get("complete") is False:
                    degraded_reasons.append("task_groups cache incomplete")
            except (json.JSONDecodeError, OSError) as exc:
                print(f"[singularity] task_groups cache unreadable, ignoring: {exc}", file=sys.stderr)
                degraded_reasons.append("task_groups cache unreadable")

        matches = []

        if exact:
            # O(1) exact match using index
            match = indexed["by_title_lower"].get(name)
            if match:
                # Enrich with task_group_id
                project_id = match["id"]
                match_copy = match.copy()
                match_copy["task_group_id"] = task_groups_mapping.get(project_id)
                matches.append(match_copy)
        else:
            # Partial match - still need to iterate, but more efficient
            for p in indexed["raw"]:
                title_lower = p.get("title", "").lower()
                if name in title_lower:
                    # Enrich with task_group_id
                    project_id = p["id"]
                    p_copy = p.copy()
                    p_copy["task_group_id"] = task_groups_mapping.get(project_id)
                    matches.append(p_copy)

        missing_task_groups = [
            match["id"]
            for match in matches
            if not match.get("task_group_id")
        ]
        if missing_task_groups:
            degraded_reasons.append(
                "task_group_id missing for "
                + ", ".join(sorted(missing_task_groups))
            )

        return {
            "matches": matches,
            "degraded": bool(degraded_reasons),
            "reason": "; ".join(degraded_reasons) if degraded_reasons else None,
            "task_groups_complete": bool(
                task_groups_file.exists()
                and tg_info is not None
                and tg_info["meta"] is not None
                and tg_info["meta"].get("complete") is True
            ),
        }

    # First attempt
    search_result = search_project()
    matches = search_result["matches"] if search_result else None

    missing_task_group_ids = [
        match["id"]
        for match in (matches or [])
        if not match.get("task_group_id")
    ]
    if (
        missing_task_group_ids
        and search_result
        and search_result["task_groups_complete"]
    ):
        _refresh_task_group_mappings(client, missing_task_group_ids)
        search_result = search_project()
        matches = search_result["matches"] if search_result else None

    if matches:
        result = {
            "found": True,
            "count": len(matches),
            "projects": matches,
            "cache_validated": cache_sync["validated"],
            "cache_refreshed": cache_sync["refreshed"],
        }
        if cache_rebuilt_before_search:
            result["cache_rebuilt"] = True
        if search_result["degraded"]:
            result["degraded"] = True
            result["reason"] = search_result["reason"]
        return result

    # Cache miss → rebuild
    print(f"[singularity] Project '{name}' not found in cache, rebuilding...", file=sys.stderr)
    _rebuild_references_handler(client, None, {})

    # Second attempt
    search_result = search_project()
    matches = search_result["matches"] if search_result else None

    if matches:
        result = {
            "found": True,
            "count": len(matches),
            "projects": matches,
            "cache_rebuilt": True,
            "cache_validated": cache_sync["validated"],
            "cache_refreshed": cache_sync["refreshed"],
        }
        if search_result["degraded"]:
            result["degraded"] = True
            result["reason"] = search_result["reason"]
        return result

    result = {
        "found": False,
        "count": 0,
        "projects": [],
        "cache_rebuilt": True,
        "cache_validated": cache_sync["validated"],
        "cache_refreshed": cache_sync["refreshed"],
        "message": f"Project '{name}' not found even after cache rebuild"
    }
    if search_result and search_result["degraded"]:
        result["degraded"] = True
        result["reason"] = search_result["reason"]
    return result


def _find_tag_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    """Find tag by name using indexed search. Rebuild cache on miss and retry."""
    name = args.get("name", "").lower()
    exact = args.get("exact", False)

    if not name:
        raise ValueError("name is required")

    def search_tag():
        """Search in indexed cache."""
        indexed = _load_indexed_tags()
        if not indexed:
            return None

        degraded = bool(indexed["metadata"].get("degraded"))
        matches = []

        if exact:
            # O(1) exact match using index
            match = indexed["by_title_lower"].get(name)
            if match:
                matches.append(match)
        else:
            # Partial match - still need to iterate, but more efficient
            for t in indexed["raw"]:
                title_lower = t.get("title", "").lower()
                if name in title_lower:
                    matches.append(t)

        return {
            "matches": matches,
            "degraded": degraded,
            "reason": "cache incomplete" if degraded else None,
        }

    # First attempt
    search_result = search_tag()
    matches = search_result["matches"] if search_result else None

    if matches:
        result = {
            "found": True,
            "count": len(matches),
            "tags": matches
        }
        if search_result["degraded"]:
            result["degraded"] = True
            result["reason"] = search_result["reason"]
        return result

    # Cache miss → rebuild
    print(f"[singularity] Tag '{name}' not found in cache, rebuilding...", file=sys.stderr)
    _rebuild_references_handler(client, None, {})

    # Second attempt
    search_result = search_tag()
    matches = search_result["matches"] if search_result else None

    if matches:
        result = {
            "found": True,
            "count": len(matches),
            "tags": matches,
            "cache_rebuilt": True
        }
        if search_result["degraded"]:
            result["degraded"] = True
            result["reason"] = search_result["reason"]
        return result

    result = {
        "found": False,
        "count": 0,
        "tags": [],
        "cache_rebuilt": True,
        "message": f"Tag '{name}' not found even after cache rebuild"
    }
    if search_result and search_result["degraded"]:
        result["degraded"] = True
        result["reason"] = search_result["reason"]
    return result


def _task_full_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    """Get task with its note (batch: task_get + note_list).

    Accepts task ID (T-xxx) or Singularity URL:
    - singularityapp://?&page=any&id=T-...
    - https://web.singularity-app.com/#/?&id=T-...
    """
    import re
    from urllib.parse import urlparse, parse_qs

    task_id_input = args.get("task_id", "").strip()

    # Parse URL if needed
    task_id = task_id_input
    if "://" in task_id_input:
        # URL format: extract id parameter
        parsed = urlparse(task_id_input)

        if parsed.scheme == "singularityapp":
            # singularityapp://?&page=any&id=T-xxx
            qs = parse_qs(parsed.query)
            if "id" in qs:
                task_id = qs["id"][0]
        elif "singularity-app.com" in parsed.netloc:
            # https://web.singularity-app.com/#/?&id=T-xxx
            # Fragment contains query string
            fragment = parsed.fragment
            if "?" in fragment:
                qs_part = fragment.split("?", 1)[1]
                qs = parse_qs(qs_part)
                if "id" in qs:
                    task_id = qs["id"][0]

        # Extract T-UUID from id (may have timestamp suffix like -20260222)
        match = re.search(r'(T-[0-9a-f-]+)', task_id)
        if match:
            task_id = match.group(1)

    if not task_id.startswith("T-"):
        return {"error": f"Invalid task ID: {task_id_input}"}

    # quote() guards against path injection if the ID contains slashes.
    task = client.get(f"/v2/task/{quote(task_id, safe='')}")

    # Resolve note via note_resolver. Prefer the task's own `note` field as the
    # source of truth for the note ID (the /v2/note?containerId= filter is
    # ignored server-side — see resolve_note docstring).
    task_note_id = task.get("note") if isinstance(task, dict) else None
    note_result = resolve_note(client, task_id, note_id=task_note_id)

    return {
        "task": task,
        "note": note_result["raw"],          # back-compat: full note dict or None
        # Additive status metadata retained for caller compatibility:
        "status": note_result["status"],     # "ok" | "degraded" | "unsupported"
        "partial": note_result["partial"],
        "note_status": note_result["note_status"],
        "warnings": note_result["warnings"],
    }


def _project_tasks_full_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    """Return all tasks of a project with notes, using a server-side filter."""
    project_id = args.get("project_id", "").strip()
    include_notes = args.get("include_notes", True)

    if not project_id.startswith("P-"):
        return {"error": f"Invalid project ID: {project_id}"}

    # The API supports a server-side `projectId` filter.
    # query param (RESOURCES['task'].list_filter_fields) — no client-side scan needed.
    pag = iterate_pages(
        client, "/v2/task",
        params={"projectId": project_id},
        wrapper_keys=["tasks", "items"],
    )
    tasks = pag["items"]
    pag_partial = pag["partial"]
    pag_warnings = list(pag["warnings"])

    if not include_notes:
        return {
            "project_id": project_id,
            "total_tasks": len(tasks),
            "tasks": tasks,
            "status": "degraded" if pag_partial else "ok",
            "partial": pag_partial,
            "note_status": "skipped",
            "warnings": pag_warnings,
        }

    # Resolve notes for all tasks through the shared guard.
    tasks_with_notes = []
    aggregated_warnings: list = list(pag_warnings)
    any_degraded = pag_partial
    for task in tasks:
        task_id = task["id"]
        note_result = resolve_note(client, task_id, note_id=task.get("note"))
        note = note_result["raw"]
        if note_result["status"] != "ok":
            any_degraded = True
            aggregated_warnings.extend(
                f"task {task_id}: {w}" for w in note_result["warnings"]
            )
        tasks_with_notes.append({
            "task": task,
            "note": note,
        })

    return {
        "project_id": project_id,
        "total_tasks": len(tasks_with_notes),
        "tasks_with_notes": tasks_with_notes,
        "status": "degraded" if any_degraded else "ok",
        "partial": pag_partial,
        "note_status": "ok",
        "warnings": aggregated_warnings,
    }


def _inbox_list_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    """Return inbox tasks using a paginated scan with a page limit.

    No server-side "inbox" filter exists — we scan pages and filter client-side.
    `page_limit` (default 10 → 10k items) caps the scan; if reached, partial=True.
    """
    include_notes = args.get("include_notes", False)
    page_limit = args.get("page_limit", 10)

    pag = iterate_pages(
        client, "/v2/task",
        wrapper_keys=["tasks", "items"],
        max_pages=int(page_limit),
    )
    all_tasks = pag["items"]
    pag_partial = pag["partial"]
    pag_warnings = list(pag["warnings"])

    # Keep legacy tasks with projectId == 0; only None and "" mean inbox.
    # excluded; inbox semantics historically = "no project assigned".
    inbox_tasks = [
        t for t in all_tasks
        if t.get("projectId") in (None, "")
    ]

    if not include_notes:
        return {
            "total": len(inbox_tasks),
            "tasks": inbox_tasks,
            "status": "degraded" if pag_partial else "ok",
            "partial": pag_partial,
            "note_status": "skipped",
            "warnings": pag_warnings,
        }

    # Resolve notes for all inbox tasks through the shared guard.
    tasks_with_notes = []
    aggregated_warnings: list = list(pag_warnings)
    any_degraded = pag_partial
    for task in inbox_tasks:
        task_id = task["id"]
        note_result = resolve_note(client, task_id, note_id=task.get("note"))
        if note_result["status"] != "ok":
            any_degraded = True
            aggregated_warnings.extend(
                f"task {task_id}: {w}" for w in note_result["warnings"]
            )

        tasks_with_notes.append({
            "task": task,
            "note": note_result["raw"],
        })

    return {
        "total": len(tasks_with_notes),
        "tasks_with_notes": tasks_with_notes,
        "status": "degraded" if any_degraded else "ok",
        "partial": pag_partial,
        "note_status": "ok",
        "warnings": aggregated_warnings,
    }


__all__ = [
    '_load_indexed_projects',
    '_load_indexed_tags',
    '_generate_meta_template_handler',
    '_find_project_handler',
    '_find_tag_handler',
    '_task_full_handler',
    '_project_tasks_full_handler',
    '_inbox_list_handler',
]
