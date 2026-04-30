# Contract Baseline (T0.7)

## 1. Canonical Sources

| URL | Status | Notes |
|---|---|---|
| `https://api.singularity-app.com/v2/api-json` | primary | OpenAPI 3.0 v2 |
| `https://api.singularity-app.com/v2/api` | secondary | Swagger UI |
| `https://api.singularity-app.com/api-json` | deprecated for this skill | v1; do not use as the v2 client contract |

## 2. Base URL Used by Skill

- Base URL from `config.json`: `https://api.singularity-app.com`
- Endpoint paths: `/v2/{resource}`

## 3. Supported Endpoints

Source: `cli.py:149-297` (`RESOURCES`) plus generic CRUD dispatch at `cli.py:1026-1045`.

| Resource | Path | Operations |
|---|---|---|
| `project` | `/v2/project` | list, get, create, update, delete |
| `task_group` | `/v2/task-group` | list, get, create, update, delete |
| `task` | `/v2/task` | list, get, create, update, delete |
| `note` | `/v2/note` | list, get, create, update, delete |
| `kanban_status` | `/v2/kanban-status` | list, get, create, update, delete |
| `kanban_task_status` | `/v2/kanban-task-status` | list, get, create, update, delete |
| `habit` | `/v2/habit` | list, get, create, update, delete |
| `habit_progress` | `/v2/habit-progress` | list, get, create, update, delete |
| `checklist` | `/v2/checklist-item` | list, get, create, update, delete |
| `tag` | `/v2/tag` | list, get, create, update, delete |
| `time_stat` | `/v2/time-stat` | list, get, create, update, delete, bulk_delete |

## 4. Tool Catalog Snapshot

Source: `cli.py:395-1018` (`TOOL_CATALOG`). Total count: 63.

| Category | Tools |
|---|---|
| task | `task_group_list`, `task_group_get`, `task_group_create`, `task_group_update`, `task_group_delete`, `task_list`, `task_get`, `task_create`, `task_update`, `task_delete`, `checklist_list`, `checklist_get`, `checklist_create`, `checklist_update`, `checklist_delete` |
| project | `project_list`, `project_get`, `project_create`, `project_update`, `project_delete`, `rebuild_references`, `find_project` |
| tag | `tag_list`, `tag_get`, `tag_create`, `tag_update`, `tag_delete`, `find_tag` |
| habit | `habit_list`, `habit_get`, `habit_create`, `habit_update`, `habit_delete`, `habit_progress_list`, `habit_progress_get`, `habit_progress_create`, `habit_progress_update`, `habit_progress_delete` |
| kanban | `kanban_status_list`, `kanban_status_get`, `kanban_status_create`, `kanban_status_update`, `kanban_status_delete`, `kanban_task_status_list`, `kanban_task_status_get`, `kanban_task_status_create`, `kanban_task_status_update`, `kanban_task_status_delete` |
| note | `note_list`, `note_get`, `note_create`, `note_update`, `note_delete` |
| time | `time_stat_list`, `time_stat_get`, `time_stat_create`, `time_stat_update`, `time_stat_delete`, `time_stat_bulk_delete` |
| derived | `generate_meta_template`, `task_full`, `project_tasks_full`, `inbox_list` |

## 5. Auth

- Auth method: Bearer token.
- Token source: `config.json`.

## 6. Pagination Contract

- Pagination uses `offset` + `maxCount`.
- `maxCount` maximum: 1000.
- No cursor contract in Swagger v2.

## 7. Notes API Addendum

`/v2/note` is undocumented in `v2/api-json` but works in live probes. It returns HTTP 200 with wrapper key `notes`, not wrapper key `content`. See `references/contract/notes-decision.md` and `references/contract/observed-api-shapes.json`.

## 8. Baseline Commit

`<BASELINE_COMMIT_SHA>`
