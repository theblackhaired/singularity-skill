"""Note resolution helper — Iteration 1 (T1.1 + T1.2).

Encapsulates `/v2/note` capability and parsing per Decision A in
`references/contract/notes-decision.md` (T0.3). Wrapper key is `notes`
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


def resolve_note(client, container_id: str) -> dict:
    """Fetch the (most recent) note for a given container_id.

    Per Decision A:
      - endpoint: GET /v2/note?containerId=<id>&maxCount=1
      - wrapper: response["notes"]: list
      - body of note: notes[0]["content"] (Delta-formatted text)

    Returns NoteResult dict. Never raises for documented failure modes;
    structured `degraded`/`unsupported` is preferred over exceptions.
    """
    if not container_id:
        return _empty_result(
            status="degraded",
            note_status="error",
            warnings=["empty container_id passed to resolve_note"],
        )

    try:
        resp = client.get("/v2/note", params={
            "containerId": container_id,
            "maxCount": 1,
        })
    except RuntimeError as exc:
        # SingularityClient wraps HTTPError into RuntimeError with text
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

    if not isinstance(resp, dict) or "notes" not in resp:
        return _empty_result(
            status="degraded",
            note_status="shape_mismatch",
            warnings=[
                "expected wrapper key 'notes' in /v2/note response; "
                f"got keys: {list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__}"
            ],
        )

    notes = resp.get("notes")
    if not isinstance(notes, list):
        return _empty_result(
            status="degraded",
            note_status="shape_mismatch",
            warnings=["wrapper 'notes' present but not an array"],
        )

    if not notes:
        return _empty_result(status="ok", note_status="missing")

    head = notes[0]
    if not isinstance(head, dict):
        return _empty_result(
            status="degraded",
            note_status="shape_mismatch",
            warnings=["first note in array is not an object"],
        )

    body = head.get("content")
    note_id = head.get("id")
    return _empty_result(
        status="ok",
        note_status="ok",
        content=body,
        note_id=note_id,
        raw=head,
    )


__all__ = [
    "NoteStatus",
    "ResolverStatus",
    "resolve_note",
    "note_capability_ok",
]
