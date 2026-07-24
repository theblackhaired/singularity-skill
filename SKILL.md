---
name: singularity
description: REST API client for Singularity App projects, tasks, sections, notes, tags, habits, kanban, checklists, and time tracking. Use for reading or managing Singularity data, authoritative project lookup, cache refresh, and safe task movement between projects and sections.
---

# Singularity App

Run commands from this directory. The client uses Python 3.10+ stdlib and
`config.json`.

## Start with a health check

Use these read-only checks when configuration, API compatibility, or cache
health is uncertain:

```powershell
python cli.py --doctor
python cli.py --verify-api
python cli.py --verify-cache
python cli.py --verify-metadata
```

Discover tools instead of memorizing schemas:

```powershell
python cli.py --list
python cli.py --describe task_move
python cli.py --call '{"tool":"project_list","arguments":{"max_count":10}}'
```

The runtime exposes <!-- TOOLS_COUNT_BEGIN -->65<!-- TOOLS_COUNT_END --> tools.
`tools.json` is generated external metadata, not the runtime source of truth.

## Configuration

Create ignored `config.json`:

```json
{
  "base_url": "https://api.singularity-app.com",
  "token": "YOUR_API_TOKEN",
  "read_only": false,
  "cache_ttl_days": 30
}
```

Set `read_only` to `true` to block all write tools before network access.
Setting `cache_ttl_days` to `null` disables only TTL rebuilds; live validation
inside `find_project` remains enabled.

## Choose the tool

| Need | Tool |
|---|---|
| Find a project or its UUID | `find_project` |
| List projects or children | `project_list` |
| Read or search tasks | `task_get`, `task_list`, `task_full` |
| Move a task between projects/sections | `task_move` |
| Read project tasks with notes | `project_tasks_full` |
| Read Inbox | `inbox_list` |
| Find a tag | `find_tag` |
| Refresh local references | `rebuild_references` |
| Inspect exact arguments | `--describe <tool>` |

Use generic CRUD tools for notes, habits, kanban, checklists, tags, and time
tracking. Use `--list` for their exact names.

## Project cache is never authoritative by itself

For project existence, IDs, and write preparation, always call
`find_project`. Do not make decisions from `references/projects.json`
directly.

Before searching, `find_project`:

1. Locks the project cache across local processes.
2. Requests `/v2/project` changes since the last server watermark with overlap.
3. Applies rename, move, archive, and tombstone changes atomically.
4. Compares the live project total and performs full reconciliation when it
   differs.
5. Preserves local project descriptions.
6. Returns an error rather than silently trusting stale data when validation
   fails.

Example:

```powershell
python cli.py --call '{"tool":"find_project","arguments":{"name":"ISS","exact":true}}'
```

Important response fields:

- `cache_validated`: the server check succeeded;
- `cache_refreshed`: live changes were applied;
- `cache_rebuilt`: a full reconciliation ran;
- `degraded` and `reason`: project data was found but a dependent mapping is
  incomplete.

`rebuild_references` refreshes projects, tags, and base task-group mappings.
Task groups require one query per project, so the tool waits 750 ms between
projects by default to avoid server 429 responses:

```powershell
python cli.py --call '{"tool":"rebuild_references","arguments":{}}'
```

Override `task_group_throttle_ms` only for diagnostics.

## Projects, task groups, and parent tasks

Keep these ID types distinct:

| Prefix | Entity | Task field |
|---|---|---|
| `P-*` | Project | `projectId` |
| `Q-*` | Project section/task group | `group` |
| `T-*` | Task; may parent a subtask | `parent` |

Every project normally has a base `Q-*` group. A task moved by changing only
`projectId` can retain a group from the old project and disappear from the
target project view.

## Move tasks with `task_move`

Use `task_move`, not a raw `task_update`, for cross-project moves:

```powershell
python cli.py --call '{"tool":"task_move","arguments":{"id":"T-...","project_id":"P-...","section":"В работе"}}'
python cli.py --call '{"tool":"task_move","arguments":{"id":"T-...","project_id":"P-...","section_id":"Q-..."}}'
```

Rules:

- `section` is an exact case-insensitive title resolved from the live target
  project's groups.
- `section_id` is verified through `GET /v2/task-group/{id}`.
- Reject missing, ambiguous, removed, foreign, or partially fetched sections
  before PATCH.
- Send `projectId` and `group` in one PATCH.
- Read the task back and verify both fields.
- If the target project has exactly one live group, `section` may be omitted.
- `task_update.parent` accepts only a parent task `T-*`, never a section `Q-*`.

## Create tasks correctly

For a root project task:

- provide `title` and `projectId`;
- do not set `parent`;
- set `start` for the task date;
- use `useTime: false` for a date without a time;
- do not use `deadline` when the user only requested a date.

For a subtask, set `parent` to a `T-*` task and still provide `projectId`.
Do not pass a `Q-*` group as `parent`.

After creation:

- store structured steps as checklist items;
- leave the note empty when title and checklist contain all information;
- use `task_update.note` for plain task description changes.

## Notes

The v2 notes endpoint is functional but not present in the upstream OpenAPI.
Read [references/contract/notes-decision.md](references/contract/notes-decision.md)
before changing note resolution.

Delta content must be a flat array and end with a newline:

```json
[
  {"insert": "Hello "},
  {"insert": "world", "attributes": {"bold": true}},
  {"insert": "\n"}
]
```

Do not wrap it in `{"ops": [...]}`. Validate the returned `containerId` so an
unfiltered list response can never attach another object's note.

## Other data rules

- Emoji: lowercase Unicode hex without `U+`, for example `1f680`.
- Habit status: `0` active, `1` paused, `2` completed, `3` archived.
- Time tracking source: `0` pomodoro, `1` stopwatch.
- Date-only task: `useTime=false`.
- Timed task: include an ISO timestamp with timezone.
- Notifications: use `notifies` minute offsets and `notify=1`.
- Do not set `showInBasket` unless explicitly requested.
- List endpoints use `maxCount` and `offset`; the server maximum page size is
  1000.

## Cache files

Generated and ignored:

- `references/projects.json`;
- `references/tags.json`;
- `references/task_groups.json`;
- `references/*.lock`.

Committed examples document their shape. Edit project descriptions through
`project_describe`; `project_meta.json` is only a first-import legacy fallback.

## Known limitations

- `/v2/note` is an observed capability rather than an OpenAPI contract.
- `inbox_list` scans client-side and caps work at 10,000 tasks.
- Full task-group rebuild is N+1 and therefore intentionally paced.
- Vendor rate limits are not formally documented; HTTP 429 uses bounded retry
  and preserves partial/degraded evidence.
- Cache validation protects project lookups on this local checkout. Separate
  clones or machines maintain independent caches and locks.

## Development contract

- Runtime catalog: `cli.py`.
- Generated external metadata: `tools.json`.
- Metadata generator: `scripts/regen_metadata.py`.
- Redacted live API shapes:
  `references/contract/observed-api-shapes.json`.
- Secret handling:
  `references/contract/secrets-policy.md`.

After catalog or documentation changes:

```powershell
python scripts/regen_metadata.py
python scripts/regen_metadata.py --check
python -m pytest -q
```
