# Notes API contract

## Observed behavior

- `/v2/note` works but is absent from the v2 OpenAPI schema.
- The list wrapper is `notes`; `content` belongs to each note.
- `GET /v2/note?containerId=X` does not reliably filter on the server.
- `expand=note` on a task does not embed the note.
- Observed note IDs follow `N-{containerId}`.

The redacted live response shapes are stored in
`observed-api-shapes.json`.

## Resolver rule

Resolve a task or project note through:

```text
GET /v2/note/N-{containerId}
```

If the container already carries a note ID, prefer that ID. After fetching,
require `note.containerId == requested containerId`. A mismatch must return
`shape_mismatch`; never return an unrelated note.

The capability probe may use the list endpoint, but normal resolution must not
select the first item from an unfiltered list.

## Failure behavior

- Missing note: return the documented missing/empty result.
- Endpoint unavailable: return a degraded result with the error preserved.
- Unexpected response shape: return `shape_mismatch`.
- Do not silently fall back to an arbitrary list item.
