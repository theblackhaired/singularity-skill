---
name: singularity
description: REST API client for Singularity App -- task management, projects, habits, kanban boards, notes, time tracking (56 tools)
version: 1.0.0
---

# Singularity App Skill

Direct REST API v2 client for Singularity App. No external dependencies -- uses Python stdlib only (urllib, json, ssl). Bearer token auth via `config.json`.

## Quick Router

| User wants to... | Tools to use |
|---|---|
| See all projects | `project_list` |
| Create a task | `task_group_list` (find group) then `task_create` |
| Complete a task | `task_update` with `checked: true` |
| Add checklist to task | `checklist_create` |
| Manage kanban board | `kanban_status_list`, `kanban_task_status_create` |
| Track a habit | `habit_create`, then `habit_progress_create` daily |
| Add a note to project/task | `note_create` |
| Track time | `time_stat_create` |
| Organize with tags | `tag_list`, `tag_create` |
| Find tasks in project | `task_list` with `project_id` |
| Create a notebook | `project_create` with `isNotebook: true` |
| Add note to notebook | `task_create` with `isNote: true` in notebook's task group |

## Available Tools (56)

### Projects (5 tools)

| Tool | Description |
|---|---|
| `project_list` | List projects (params: max_count, offset, include_removed, include_archived) |
| `project_get` | Get project by ID |
| `project_create` | Create project (title, note, start, end, emoji, color, parent, isNotebook, tags...) |
| `project_update` | Update project |
| `project_delete` | Delete project |

### Task Groups (5 tools)

| Tool | Description |
|---|---|
| `task_group_list` | List task groups (params: max_count, offset, include_removed, parent) |
| `task_group_get` | Get task group by ID |
| `task_group_create` | Create task group (title, parent required as P-uuid) |
| `task_group_update` | Update task group |
| `task_group_delete` | Delete task group |

### Tasks (5 tools)

| Tool | Description |
|---|---|
| `task_list` | List tasks (params: max_count, offset, project_id, parent, start_date_from/to, include_removed/archived) |
| `task_get` | Get task by ID |
| `task_create` | Create task (title, parent required; note, priority, start, deadline, tags, recurrence...) |
| `task_update` | Update task |
| `task_delete` | Delete task |

### Notes (5 tools)

| Tool | Description |
|---|---|
| `note_list` | List notes (params: max_count, offset, container_id) |
| `note_get` | Get note by ID |
| `note_create` | Create note (containerId, content as Delta array, contentType="delta") |
| `note_update` | Update note |
| `note_delete` | Delete note |

### Kanban Statuses (5 tools)

| Tool | Description |
|---|---|
| `kanban_status_list` | List kanban statuses (params: max_count, offset, project_id) |
| `kanban_status_get` | Get kanban status by ID |
| `kanban_status_create` | Create kanban status (name, projectId required) |
| `kanban_status_update` | Update kanban status |
| `kanban_status_delete` | Delete kanban status |

### Kanban Task Statuses (5 tools)

| Tool | Description |
|---|---|
| `kanban_task_status_list` | List kanban task statuses (params: task_id, status_id) |
| `kanban_task_status_get` | Get kanban task status by ID |
| `kanban_task_status_create` | Create kanban task status (taskId, statusId required) |
| `kanban_task_status_update` | Update kanban task status |
| `kanban_task_status_delete` | Delete kanban task status |

### Habits (5 tools)

| Tool | Description |
|---|---|
| `habit_list` | List habits |
| `habit_get` | Get habit by ID |
| `habit_create` | Create habit (title; color, status, description, order) |
| `habit_update` | Update habit |
| `habit_delete` | Delete habit |

### Habit Progress (5 tools)

| Tool | Description |
|---|---|
| `habit_progress_list` | List habit progress (params: habit, start_date, end_date) |
| `habit_progress_get` | Get habit progress entry by ID |
| `habit_progress_create` | Create progress entry (habit, date, progress required) |
| `habit_progress_update` | Update progress entry |
| `habit_progress_delete` | Delete progress entry |

### Checklist Items (5 tools)

| Tool | Description |
|---|---|
| `checklist_list` | List checklist items (params: parent task ID) |
| `checklist_get` | Get checklist item by ID |
| `checklist_create` | Create checklist item (parent task ID, title required) |
| `checklist_update` | Update checklist item |
| `checklist_delete` | Delete checklist item |

### Tags (5 tools)

| Tool | Description |
|---|---|
| `tag_list` | List tags (params: parent tag ID) |
| `tag_get` | Get tag by ID |
| `tag_create` | Create tag (title required; color, hotkey, parent) |
| `tag_update` | Update tag |
| `tag_delete` | Delete tag |

### Time Stats (6 tools)

| Tool | Description |
|---|---|
| `time_stat_list` | List time entries (params: date_from, date_to, related_task_id) |
| `time_stat_get` | Get time entry by ID |
| `time_stat_create` | Create time entry (start ISO, secondsPassed required; relatedTaskId, source) |
| `time_stat_update` | Update time entry |
| `time_stat_delete` | Delete time entry |
| `time_stat_bulk_delete` | Bulk delete time entries by filter (date_from, date_to, related_task_id) |

## Usage

### Step 1: Identify the right tool

### Step 2: Build the call JSON

```json
{"tool": "tool_name", "arguments": {"param1": "value1"}}
```

### Step 3: Execute

```bash
python cli.py --call '{"tool": "tool_name", "arguments": {...}}'
```

### Getting tool details

```bash
python cli.py --describe tool_name
```

## Configuration

Create `config.json` in the skill directory:

```json
{
  "base_url": "https://api.singularity-app.com",
  "token": "YOUR_API_TOKEN",
  "read_only": false
}
```

Set `"read_only": true` to block all write operations. Read tools work normally.

## Data Format Notes

### Task defaults
- Default priority = **1** (set explicitly if needed)
- Add tasks to the **base task group** of the project unless user specifies otherwise
- To find the base task group: `task_group_list` with `parent` = project ID in `P-{uuid}` format

### Emoji format
- Hex Unicode code **without prefix**: `"1f49e"` (not `"U+1F49E"` or `"\u1f49e"`)

### Note content (Delta format)
- Content must be a **flat Delta array**: `[{"insert": "text"}, {"insert": "\n"}]`
- **NOT** the Quill format `{"ops": [...]}`
- Last insert **must end with a newline** character `\n`

Example:
```json
{
  "containerId": "task-uuid",
  "content": [
    {"insert": "Hello "},
    {"insert": "world", "attributes": {"bold": true}},
    {"insert": "\n"}
  ],
  "contentType": "delta"
}
```

### Habit colors (string enum)
`red` | `pink` | `purple` | `deepPurple` | `indigo` | `lightBlue` | `cyan` | `teal` | `green` | `lightGreen` | `lime` | `yellow` | `amber` | `orange` | `deepOrange` | `brown` | `grey` | `blueGrey`

### Habit status
- `0` = active
- `1` = paused
- `2` = completed
- `3` = archived

### Time and timezone
- `useTime: false` = date-only task (no specific time)
- `useTime: true` = real time, timezone is **GMT+3** (Moscow)
- All ISO datetime strings should account for this timezone

### Notebooks and notes-in-notebooks
- A **notebook** is a project with `isNotebook: true`
- A **note inside a notebook** is a task with `isNote: true` in that notebook's task group

### Notifications
- Set `notifies: [60, 15]` for notifications at 60 and 15 minutes before
- Set `notify: 1` to enable notifications
- `alarmNotify: true` or `false` for alarm-style notification

### showInBasket
- Do **not** set `showInBasket` unless the user explicitly asks for it

### Time tracking source
- `source: 0` = pomodoro timer
- `source: 1` = stopwatch

### Pagination
- All list endpoints support `maxCount` (max 1000) and `offset`
- Default `maxCount` is 100

## Examples

### List all projects

```bash
python cli.py --call '{"tool": "project_list", "arguments": {}}'
```

### Create a project with emoji

```bash
python cli.py --call '{"tool": "project_create", "arguments": {"title": "My Project", "emoji": "1f680"}}'
```

### Create a task in a project

```bash
# 1. Find the base task group
python cli.py --call '{"tool": "task_group_list", "arguments": {"parent": "P-<project-uuid>"}}'

# 2. Create the task in that group
python cli.py --call '{"tool": "task_create", "arguments": {"title": "Buy groceries", "parent": "<task-group-id>", "priority": 1}}'
```

### Add a checklist to a task

```bash
python cli.py --call '{"tool": "checklist_create", "arguments": {"parent": "<task-id>", "title": "Step 1: Do X"}}'
python cli.py --call '{"tool": "checklist_create", "arguments": {"parent": "<task-id>", "title": "Step 2: Do Y"}}'
```

### Create a habit and log progress

```bash
python cli.py --call '{"tool": "habit_create", "arguments": {"title": "Morning run", "color": "green", "status": 0}}'
python cli.py --call '{"tool": "habit_progress_create", "arguments": {"habit": "<habit-id>", "date": "2025-01-15", "progress": 1}}'
```

### Create a note on a task

```bash
python cli.py --call '{"tool": "note_create", "arguments": {"containerId": "<task-id>", "content": [{"insert": "Meeting notes here\n"}], "contentType": "delta"}}'
```

### Track time on a task

```bash
python cli.py --call '{"tool": "time_stat_create", "arguments": {"start": "2025-01-15T10:00:00.000+03:00", "secondsPassed": 1800, "relatedTaskId": "<task-id>", "source": 1}}'
```

### Set up kanban board

```bash
# Create statuses
python cli.py --call '{"tool": "kanban_status_create", "arguments": {"name": "To Do", "projectId": "<project-id>", "kanbanOrder": 0}}'
python cli.py --call '{"tool": "kanban_status_create", "arguments": {"name": "In Progress", "projectId": "<project-id>", "kanbanOrder": 1}}'
python cli.py --call '{"tool": "kanban_status_create", "arguments": {"name": "Done", "projectId": "<project-id>", "kanbanOrder": 2}}'

# Assign task to status
python cli.py --call '{"tool": "kanban_task_status_create", "arguments": {"taskId": "<task-id>", "statusId": "<status-id>"}}'
```

---

*Direct REST API client for Singularity App.*
*No pip dependencies. Python 3.8+ stdlib only.*
