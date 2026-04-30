# Notes API model decision (T0.3)

## Decision: A — `/v2/note` undocumented but functional

## Rationale

Live probe (T0.1+T0.2 на коммите baseline, см. `observed-api-shapes.json`) показал:

| Source | Result |
|---|---|
| OpenAPI v2 (`/v2/api-json`) | endpoint `/v2/note` отсутствует |
| OpenAPI v1 (`/api-json`) | endpoint `/v1/note`, wrapper response `NoteResponseDto` с полем `content` |
| Live `GET /v2/note?containerId=<id>&maxCount=1` | **HTTP 200**, wrapper `{"notes": [...]}` |
| Live `GET /v2/task/{id}` (no expand) | поле `note` отсутствует |
| Live `GET /v2/task/{id}?expand=note` | поле `note` отсутствует (expand не работает для note) |

Вывод:
1. Endpoint `/v2/note` существует undocumented и работает.
2. Wrapper key — **`notes`** (не `content`, как читал старый код).
3. Каждый элемент `notes[*]` имеет поле `content` (body заметки в Delta-формате) + `id`, `containerId`, `modificatedDate`, `removed`, `modificated`.
4. Альтернативные пути (embedded `task.note` / `task?expand=note`) — НЕ работают.
5. Решение C (использовать `/v1/note`) отвергается: подмешивать v1 в v2-клиент создаёт дополнительный drift.

## Implementation guidance for Iteration 1

В `note_resolver.py`:

```python
def resolve_note(client, container_id):
    """Returns dict: {status, partial, note_status, content, warnings}."""
    try:
        resp = client.get("/v2/note", params={
            "containerId": container_id,
            "maxCount": 1,
        })
    except RuntimeError as exc:
        return {
            "status": "degraded",
            "note_status": "error",
            "warnings": [f"note endpoint failed: {exc}"],
            "content": None,
        }

    notes = resp.get("notes", [])  # NB: wrapper key is "notes", not "content"
    if not isinstance(notes, list):
        return {
            "status": "degraded",
            "note_status": "shape_mismatch",
            "warnings": ["expected wrapper 'notes' to be array"],
            "content": None,
        }

    if not notes:
        return {
            "status": "ok",
            "note_status": "missing",
            "content": None,
            "warnings": [],
        }

    # Each note has its own `content` field with Delta body
    body = notes[0].get("content")
    return {
        "status": "ok",
        "note_status": "ok",
        "content": body,
        "warnings": [],
    }
```

## Specific bug in current code

[cli.py:1608-1611](../../cli.py) reads `note_list.get("content", [])` — this is the **wrapper-level** key, which doesn't exist on `/v2/note` response. Always returns `[]` regardless of actual notes.

The confusion: there are TWO levels of `content`:
- ❌ wrapper level: `{"content": [...]}` — does NOT exist (this is what code wrongly assumes)
- ✅ wrapper level: `{"notes": [...]}` — actual response shape
- ✅ inside each note: `notes[i]["content"]` — the Delta body of the note

Same bug at [cli.py:1661-1663](../../cli.py) (`_project_tasks_full_handler`) and [cli.py:1705-1707](../../cli.py) (`_inbox_list_handler`).

## Drift / risks

- `/v2/note` is **undocumented**. The skill must run probe checks at startup or via `--doctor` to detect if the endpoint disappears in future API versions.
- Pagination behavior of `/v2/note` matches other v2 endpoints (`maxCount` parameter accepted; full pagination contract — verify in T2.* with multi-page test).
- Filtering by `containerId` is the only filter empirically verified. Other filters (e.g. `removed=false`) — NOT verified, do not assume.

## Capability check (must run before relying on resolver)

```python
def note_capability_ok(client) -> bool:
    """Ping /v2/note with minimal params; verify wrapper shape."""
    try:
        resp = client.get("/v2/note", params={"maxCount": 0})
    except Exception:
        return False
    return isinstance(resp, dict) and "notes" in resp and isinstance(resp["notes"], list)
```

Used in `--doctor` and as gate before derived tools call resolver.
