---
name: singularity
description: REST API client for Singularity App -- task management, projects, habits, kanban boards, notes, time tracking (64 tools)
version: 1.2.0
---

## Проверка готовности (при каждом вызове)

Перед выполнением любого запроса проверь наличие данных:

1. **`references/projects.json`** — если нет → запусти `rebuild_references()`
2. **`references/tags.json`** — если нет → запусти `rebuild_references()`
3. **`references/project_meta.json`** — если нет → создать пустой `{}`
4. **`references/tag_meta.json`** — если нет → создать пустой `{}`

Если все файлы на месте — работай как обычно. Если чего-то не хватает — сначала заполни недостающее, потом выполняй запрос.

## ⚡ ПРАВИЛО ПРИОРИТЕТА КЭША

**КРИТИЧНО: ВСЕГДА используй кэш вместо API запросов!**

| Задача | ❌ НЕ ДЕЛАЙ | ✅ ДЕЛАЙ |
|--------|-------------|----------|
| Найти проект по имени | `project_list` + фильтрация | Read `references/projects.json` + поиск |
| Найти тег по имени | `tag_list` + фильтрация | Read `references/tags.json` + поиск |
| Получить UUID проекта | API запрос | Read кэша + find_project |
| Список подпроектов | `project_list(parent=...)` | Read кэша + filter by parent |
| Проверить существование | API запрос | Read кэша |

**Когда использовать API:**
- Создание/изменение/удаление данных (write operations)
- Получение задач, заметок, привычек (нет в кэше)
- Получение динамических данных (статусы канбан, прогресс привычек)

**Кэш содержит:**
- ✅ Все проекты с полной структурой (parent-child)
- ✅ Все теги с полной структурой
- ✅ Описания из meta файлов
- ❌ НЕТ задач, заметок, привычек

## Project Cache

A project tree with IDs is available at `projects_cache.md` in this skill directory.
**Always check it first** before calling `project_list` to save context tokens.

The cache is **auto-managed**:
- On first use (cache missing) it is built automatically
- Refreshed silently every 7 days before any `--call` invocation
- Refresh messages go to stderr and do not pollute JSON output

Manual refresh:
```bash
python cli.py --refresh-cache
```

Cache location: `projects_cache.md` (next to `cli.py`).
Last update timestamp stored in `config.json` as `"cache_updated": "2026-02-19T16:30:00"`.

# Singularity App Skill

Direct REST API v2 client for Singularity App. No external dependencies -- uses Python stdlib only (urllib, json, ssl). Bearer token auth via `config.json`.

## Что возвращают get-запросы

### task_get и note_get
Возвращают **полный объект** из API включая:
- `note` — описание
- `tags` — массив ID тегов
- `deadline` — дедлайн
- `parent` — ID родительской задачи/группы
- все остальные поля задачи

### Подзадачи
**НЕ возвращаются вложенно** в task_get. Для получения подзадач используй:
```bash
python cli.py --call '{"tool":"task_list","arguments":{"parent":"T-<task-id>"}}'
```

То есть отдельный запрос с фильтром `parent`.

## Quick Router

| User wants to... | Tools to use |
|---|---|
| See all projects | Read `references/projects.json` (кэш) |
| Get subprojects of "В работе" | Read кэша, filter by `parent` ID |
| Create a task | `task_group_list` (find group) then `task_create` |
| Complete a task | `task_update` with `checked: true` |
| Add checklist to task | `checklist_create` |
| Manage kanban board | `kanban_status_list`, `kanban_task_status_create` |
| Track a habit | `habit_create`, then `habit_progress_create` daily |
| Add a note to project/task | `note_create` |
| Track time | `time_stat_create` |
| Organize with tags | Read `references/tags.json` (кэш) |
| Find tasks in project | `task_list` with `project_id` |
| Create a notebook | `project_create` with `isNotebook: true` |
| Add note to notebook | `task_create` with `isNote: true` in notebook's task group |
| UUID проекта по имени | `find_project(name="ISS")` или Read кэша |
| UUID тега по имени | `find_tag(name="AI")` или Read кэша |
| Обновить справочники | `rebuild_references()` |
| Сгенерировать шаблон meta | `generate_meta_template(type="projects"/"tags")` |
| Получить задачу с заметкой | `task_full(task_id="T-xxx")` или передать Singularity URL |
| Все задачи проекта с заметками | `project_tasks_full(project_id="P-xxx", include_notes=true)` |
| Посмотреть задачи в Inbox | `inbox_list()` — все задачи без projectId |
| Предложить распределение Inbox | `inbox_suggest()` — анализ и предложения проектов/тегов |

## Available Tools (64)

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

### References (4 tools)

| Tool | Description |
|---|---|
| `rebuild_references` | Regenerate references cache (projects.json, tags.json) from API and merge descriptions from meta files |
| `generate_meta_template` | Generate meta template file with _title fields for easy editing (type: 'projects' or 'tags') |
| `find_project` | Find project by name with auto-rebuild on cache miss (name, exact) |
| `find_tag` | Find tag by name with auto-rebuild on cache miss (name, exact) |

### Batch Operations (2 tools)

| Tool | Description |
|---|---|
| `task_full` | Get task with its note (batch: task_get + note_list). Accepts task ID or Singularity URL (singularityapp:// or https://web.singularity-app.com/) |
| `project_tasks_full` | Get all tasks of a project with their notes (batch: task_list + note_list for all tasks). Params: project_id (required), include_notes (default: true) |

### Inbox Tools (2 tools)

| Tool | Description |
|---|---|
| `inbox_list` | Get all tasks in Inbox (tasks without projectId). Returns up to 1000 tasks. Params: include_notes (default: false) |
| `inbox_suggest` | Suggest project/tag assignments for Inbox tasks based on title/note analysis using cached projects and tags. Params: task_ids (optional list), min_confidence (default: 0.3). Returns suggestions sorted by confidence score |

## Справочники (references/)

Предгенерированные JSON-файлы для быстрого поиска UUID без API-вызовов.

| Файл | Содержимое | Обновление |
|------|------------|------------|
| `references/projects.json` | Все проекты: id, title, emoji, color, parent, isNotebook, archived, description | `rebuild_references()` |
| `references/tags.json` | Все теги: id, title, color, hotkey, parent, description | `rebuild_references()` |
| `references/task_groups.json` | Маппинг project_id → base_task_group_id для быстрого создания задач | `rebuild_references()` |
| `references/project_meta.json` | Ручные описания проектов (назначение) | Редактировать вручную |
| `references/tag_meta.json` | Ручные описания тегов (назначение) | Редактировать вручную |

### Как использовать

1. **Вместо `project_list()`** — читай `references/projects.json` для получения UUID и описания проекта
2. **Вместо `tag_list()`** — читай `references/tags.json` для получения UUID тега
3. **Для создания задачи** — используй `find_project()` чтобы получить `task_group_id` вместо API запроса `task_group_list`
4. **После изменения проектов/тегов** — вызови `rebuild_references()` для обновления кэша

### Производительность

Кэш использует индексированный поиск для максимальной скорости:
- **Exact match** в `find_project`/`find_tag`: O(1) вместо O(n) благодаря индексу `by_title_lower`
- **Поиск по parent**: O(1) через индекс `by_parent`
- **Создание задачи**: ~1800ms экономии (не нужен API запрос `task_group_list`)

### Автообновление кэша

Кэш автоматически обновляется если:
1. **Файлы отсутствуют** — при первом запуске или после удаления
2. **Кэш устарел** — старше `cache_ttl_days` из config.json (по умолчанию 30 дней)
3. **Cache miss** — проект/тег не найден в кэше (будет реализовано при поиске)

**Настройка TTL в config.json:**
```json
{
  "token": "...",
  "cache_ttl_days": 30  // Обновлять кэш каждые 30 дней
}
```

Установить `null` чтобы отключить TTL (только cache miss и ручное обновление).

**Ручное обновление:**
```bash
python cli.py --call '{"tool":"rebuild_references","arguments":{}}'
```

Логи обновления выводятся в stderr и не мешают JSON output.

### Cache-Miss Logic (поиск с автообновлением)

Инструменты `find_project` и `find_tag` автоматически обновляют кэш если проект/тег не найден:

1. **Поиск в кэше** — ищет проект/тег по имени (case-insensitive)
2. **Cache miss** — если не найден → автоматически вызывает `rebuild_references()`
3. **Повторный поиск** — ищет снова в обновлённом кэше
4. **Результат** — возвращает найденные элементы или сообщение об отсутствии

**Примеры:**

```bash
# Найти проект ISS (partial match)
python cli.py --call '{"tool":"find_project","arguments":{"name":"ISS"}}'

# Точное совпадение
python cli.py --call '{"tool":"find_project","arguments":{"name":"ISS","exact":true}}'

# Найти тег AI
python cli.py --call '{"tool":"find_tag","arguments":{"name":"AI"}}'
```

**Формат ответа:**
```json
{
  "found": true,
  "count": 3,
  "projects": [...],
  "cache_rebuilt": false  // true если кэш обновлялся
}
```

Это универсальный способ работы с динамически меняющимися проектами (например, Jira интеграция).

### project_meta.json / tag_meta.json — правила описаний

Файлы содержат ручные аннотации. Ключ — UUID, значение — объект с полем `description`.

**Формат:**
```json
{
  "UUID-проекта": {
    "description": "Краткое описание назначения проекта"
  }
}
```

**Правила генерации description:**
- Описание должно объяснять **для чего** используется проект/тег
- Указывать основные задачи/цели
- Максимум 1 строка, ~5-15 слов
- Писать на русском

**Примеры (проекты):**
- `"Рабочие задачи и проекты"`
- `"Личные дела, покупки, здоровье"`
- `"Еженедельное планирование"`

**Примеры (теги):**
- `"Срочные задачи, требующие немедленного внимания"`
- `"Задачи, ожидающие ответа от других"`

При `rebuild_references()` описания из meta файлов автоматически мержатся в `projects.json` / `tags.json` (поле `description`, null если не задано).

**Поле `_title` для удобства:**

При ручном редактировании meta файлов используй поле `_title` (с подчёркиванием) для справки:

```json
{
  "uuid-проекта": {
    "_title": "Название проекта",  // для удобства, игнорируется при merge
    "description": "Описание назначения"
  }
}
```

Поля начинающиеся с `_` (подчёркивание) игнорируются при `rebuild_references` и не попадают в итоговый кэш. Используй их для своих заметок и удобства редактирования.

**Генерация шаблона meta файла:**

Вместо ручного создания можно сгенерировать шаблон со всеми UUID и названиями:

```bash
# Для проектов
python cli.py --call '{"tool":"generate_meta_template","arguments":{"type":"projects"}}'

# Для тегов
python cli.py --call '{"tool":"generate_meta_template","arguments":{"type":"tags"}}'
```

Это создаст (или обновит) `project_meta.json` / `tag_meta.json` с полем `_title` для каждого элемента. Вам останется только заполнить `description`.

**ВАЖНО:** Если meta файл уже существует, добавь `"overwrite": true` чтобы перезаписать:
```bash
python cli.py --call '{"tool":"generate_meta_template","arguments":{"type":"tags","overwrite":true}}'
```

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

### Task creation checklist

When creating a task, **always** provide:
1. `title` — заголовок задачи
2. `projectId` — ID проекта (`P-{uuid}`). **Обязательно указывать**, даже если задача — подзадача
3. `parent` — **только для подзадач**: ID родительской задачи (`T-{uuid}`). Для задач в **корне проекта** — **НЕ указывать `parent`**, достаточно `projectId`. `Q-...` (task group) **не работает** как parent
4. `start` — дата задачи (не deadline!). Формат: `"2026-02-20"` для даты, ISO для времени
5. `useTime: false` — если нужна только дата, без конкретного времени
6. **НЕ ставить `deadline`**, если пользователь просит дату — это `start`

After task creation:
- Структурированные пункты → `checklist_create` (не текстом в описание)
- Описание (`note`) оставлять пустым, если вся информация уже в заголовке + чеклисте
- Если нужно описание — использовать `task_update` с `note` (строка), не `note_create` (Delta format часто ломается)

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

### Find subprojects using cache (RECOMMENDED)

```python
# Вместо API запроса - читай кэш
import json

with open('references/projects.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# Найти проект "В работе"
target = next(p for p in data['projects'] if p['title'] == 'В работе')
target_id = target['id']

# Получить все подпроекты
children = [p for p in data['projects'] if p.get('parent') == target_id]

for p in children:
    print(f"• {p['title']}")
```

**Результат:** Мгновенный ответ без API запроса ⚡

### List all projects (use cache instead!)

```bash
# ❌ НЕ ДЕЛАЙ ТАК - медленно, расточительно
python cli.py --call '{"tool": "project_list", "arguments": {}}'

# ✅ ДЕЛАЙ ТАК - быстро, эффективно
# Read references/projects.json напрямую
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
