"""Deterministic note resolution helper.

Encapsulates the observed `/v2/note` behavior documented in
`references/contract/notes-decision.md`. Wrapper key is `notes`
(undocumented v2 endpoint), each note has `content` field with body Delta.

Public:
    resolve_note(client, container_id) -> NoteResult
    note_capability_ok(client) -> bool
    NoteStatus  (literal of allowed status strings)

Returned dict shape (additive — old call sites stay backward compatible):
    {
        "status":       "ok" | "degraded" | "unsupported",
        "partial":      bool,
        "note_status":  "ok" | "missing" | "skipped" | "error" | "shape_mismatch",
        "content":      str | None,         # Delta body of the note (raw)
        "note_id":      str | None,
        "raw":          dict | None,        # full note object from API (back-compat)
        "warnings":     [str, ...],
    }
"""

from typing import Any, Optional


# Allowed string literals (intentionally simple — no Enum dependency outside stdlib)
NoteStatus = ("ok", "missing", "skipped", "error", "shape_mismatch")
ResolverStatus = ("ok", "degraded", "unsupported")


def _empty_result(
    status: str = "ok",
    note_status: str = "missing",
    warnings: Optional[list] = None,
    content: Any = None,
    note_id: Optional[str] = None,
    raw: Optional[dict] = None,
    partial: bool = False,
) -> dict:
    """Build a structured NoteResult with all keys present."""
    return {
        "status": status,
        "partial": partial,
        "note_status": note_status,
        "content": content,
        "note_id": note_id,
        "raw": raw,
        "warnings": list(warnings or []),
    }


def note_capability_ok(client) -> bool:
    """Capability ping — endpoint reachable AND wrapper shape matches.

    Cheap probe with `maxCount=0` first; if endpoint rejects empty params
    (HTTP 400), tries with a temporary harmless containerId of empty string.
    Returns False on any unexpected shape, network error, or 404.
    """
    try:
        resp = client.get("/v2/note", params={"maxCount": 1})
    except Exception:  # noqa: BLE001 — capability check must not raise
        return False
    if not isinstance(resp, dict):
        return False
    notes = resp.get("notes")
    return isinstance(notes, list)


def resolve_note(client, container_id: str, note_id: Optional[str] = None) -> dict:
    """Fetch the note for a given container_id.

    Implementation note (bug-fix 2026-05-22):
      `GET /v2/note?containerId=X` is NOT filtered server-side — the API
      returns an arbitrary first note and ignores the `containerId` query
      parameter, so the previous list-then-pick-[0] approach handed back
      unrelated notes. Verified empirically on T-60ac3a52-... where the
      list endpoint returned a project note from a different container.

    The fix uses the deterministic single-resource endpoint:
      GET /v2/note/{note_id}
    where `note_id` is either passed in explicitly (preferred — taken from
    `task["note"]` by the caller) or derived from the invariant
    `note.id == "N-" + note.containerId`. A post-fetch guard verifies the
    returned `containerId` matches the requested one, so any future
    schema drift surfaces as `shape_mismatch` instead of silent wrong-data.
    """
    if not container_id:
        return _empty_result(
            status="degraded",
            note_status="error",
            warnings=["empty container_id passed to resolve_note"],
        )

    resolved_note_id = note_id or f"N-{container_id}"

    try:
        from urllib.parse import quote as _quote
        resp = client.get(f"/v2/note/{_quote(resolved_note_id, safe='')}")
    except RuntimeError as exc:
        # SingularityClient wraps HTTPError into RuntimeError("HTTP <code> ...").
        # 404 → note simply doesn't exist for this container → not an error.
        msg = str(exc)
        if "HTTP 404" in msg:
            return _empty_result(status="ok", note_status="missing")
        return _empty_result(
            status="degraded",
            note_status="error",
            warnings=[f"note endpoint failed: {exc}"],
        )
    except Exception as exc:  # noqa: BLE001 — defensive
        return _empty_result(
            status="degraded",
            note_status="error",
            warnings=[f"note endpoint raised {type(exc).__name__}: {exc}"],
        )

    if not isinstance(resp, dict):
        return _empty_result(
            status="degraded",
            note_status="shape_mismatch",
            warnings=[
                f"expected dict from /v2/note/{resolved_note_id}; "
                f"got {type(resp).__name__}"
            ],
        )

    # Some backends return {} for missing rather than 404.
    if not resp or ("id" not in resp and "content" not in resp):
        return _empty_result(status="ok", note_status="missing")

    resp_container = resp.get("containerId")
    if resp_container and resp_container != container_id:
        return _empty_result(
            status="degraded",
            note_status="shape_mismatch",
            warnings=[
                f"containerId mismatch: requested {container_id}, "
                f"got {resp_container}"
            ],
            raw=resp,
            note_id=resp.get("id"),
        )

    return _empty_result(
        status="ok",
        note_status="ok",
        content=resp.get("content"),
        note_id=resp.get("id"),
        raw=resp,
    )


__all__ = [
    "NoteStatus",
    "ResolverStatus",
    "resolve_note",
    "note_capability_ok",
]
