"""Pagination helper — Iteration 2 (T2.1).

Single source of truth for offset+maxCount paging. Replaces hardcoded
`maxCount=1000` calls scattered across handlers. Surfaces `partial: true`
when the caller-imposed `max_pages` is hit, so consumers can distinguish
"complete result" from "first N items".

Public API:

    iterate_pages(
        client,
        path: str,
        params: dict | None = None,
        page_size: int = 1000,
        max_pages: int | None = None,
        wrapper_keys: list[str] | None = None,
        throttle_ms: int = 0,
    ) -> PaginationResult

Returns a dict (TypedDict shape):
    {
        "items":          [...],         # aggregated entries
        "partial":        bool,          # True iff truncated by max_pages
        "fetched_pages":  int,
        "fetched_items":  int,
        "wrapper_key":    str | None,    # which key matched
        "warnings":       [str, ...],
    }

Notes:
- The Singularity API caps `maxCount` at 1000 (per OpenAPI v2 docs).
  We default to 1000 to minimise round-trips. Lower values are allowed.
- Retry-After / 429 handling lives in `SingularityClient._request`
  (internal exponential backoff). The paginator only adds an optional
  `throttle_ms` sleep between successful pages for cooperative pacing.
- Wrapper key auto-detect tries common conventions seen in the v2 API:
  `tasks`, `projects`, `tags`, `notes`, `taskGroups`, `items`.
  Caller may override via `wrapper_keys`.
"""

from __future__ import annotations

import time
from typing import Any


_DEFAULT_WRAPPER_KEYS = (
    "tasks", "projects", "tags", "notes",
    "taskGroups", "kanbanStatuses", "habits", "checklists",
    "timeStats", "items",
)


def _extract_items(body: Any, wrapper_keys: tuple[str, ...]) -> tuple[list, str | None]:
    """Return (items_list, matched_key). Handles list or dict response."""
    if isinstance(body, list):
        return body, None
    if not isinstance(body, dict):
        return [], None
    for k in wrapper_keys:
        v = body.get(k)
        if isinstance(v, list):
            return v, k
    # Last resort — first list-valued field at top level
    for k, v in body.items():
        if isinstance(v, list):
            return v, k
    return [], None


def iterate_pages(
    client,
    path: str,
    params: dict | None = None,
    page_size: int = 1000,
    max_pages: int | None = None,
    wrapper_keys: "list[str] | tuple[str, ...] | None" = None,
    throttle_ms: int = 0,
) -> dict:
    """Iterate paged endpoint via offset+maxCount; aggregate items.

    See module docstring for return shape and behaviour.
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    if page_size > 1000:
        # API hard limit per v2/api-json. Don't silently exceed.
        page_size = 1000

    keys = tuple(wrapper_keys) if wrapper_keys else _DEFAULT_WRAPPER_KEYS

    items: list = []
    warnings: list[str] = []
    matched_key: str | None = None
    fetched_pages = 0
    offset = 0

    # Safety cap defends against buggy server returning the same page repeatedly
    # (security-review LOW finding). Cap is high enough for legitimate full
    # scans (10k pages × 1000 items = 10M records) but bounded.
    HARD_PAGE_CAP = 10_000

    base_params = dict(params or {})
    # Strip caller-provided pagination params — paginator owns them
    for legacy in ("maxCount", "max_count", "offset", "limit"):
        base_params.pop(legacy, None)

    while True:
        if fetched_pages >= HARD_PAGE_CAP:
            warnings.append(
                f"hard_page_cap_hit at {HARD_PAGE_CAP} pages — "
                f"possible server-side pagination bug; aborting"
            )
            return {
                "items": items,
                "partial": True,
                "fetched_pages": fetched_pages,
                "fetched_items": len(items),
                "wrapper_key": matched_key,
                "warnings": warnings,
            }
        if max_pages is not None and fetched_pages >= max_pages:
            warnings.append(
                f"truncated at page_limit={max_pages} "
                f"({fetched_pages * page_size} items fetched)"
            )
            return {
                "items": items,
                "partial": True,
                "fetched_pages": fetched_pages,
                "fetched_items": len(items),
                "wrapper_key": matched_key,
                "warnings": warnings,
            }

        page_params = dict(base_params)
        page_params["maxCount"] = page_size
        page_params["offset"] = offset

        try:
            body = client.get(path, params=page_params)
        except Exception as exc:  # noqa: BLE001 — surface up as warning
            warnings.append(
                f"page_fetch_failed at offset={offset}: "
                f"{type(exc).__name__}: {exc}"
            )
            return {
                "items": items,
                "partial": True,
                "fetched_pages": fetched_pages,
                "fetched_items": len(items),
                "wrapper_key": matched_key,
                "warnings": warnings,
            }

        page_items, page_key = _extract_items(body, keys)
        if matched_key is None and page_key is not None:
            matched_key = page_key
        elif matched_key is not None and page_key is not None and page_key != matched_key:
            warnings.append(
                f"wrapper_key changed mid-iteration: "
                f"{matched_key!r} -> {page_key!r}"
            )

        items.extend(page_items)
        fetched_pages += 1

        if len(page_items) < page_size:
            # Short page = end of stream
            break

        offset += page_size

        if throttle_ms > 0:
            time.sleep(throttle_ms / 1000.0)

    return {
        "items": items,
        "partial": False,
        "fetched_pages": fetched_pages,
        "fetched_items": len(items),
        "wrapper_key": matched_key,
        "warnings": warnings,
    }


__all__ = ["iterate_pages"]
