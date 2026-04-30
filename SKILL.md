---
name: singularity
description: REST API client for Singularity App -- task management, projects, habits, kanban boards, notes, time tracking (<!-- TOOLS_COUNT_BEGIN -->64<!-- TOOLS_COUNT_END --> tools)
version: 1.5.0
---

## Self-checks (read-only, no side effects)

```bash
python cli.py --doctor             # 8 sanity checks: config, gitignore, base_url, OpenAPI, /v2/note capability, cache files, contract baseline
python cli.py --verify-cache       # references/*.json schema_version, complete=True, no legacy
python cli.py --verify-metadata    # tools.json must match runtime TOOL_CATALOG (no drift)
python cli.py --verify-api         # live API smoke: 6 canonical endpoints reachable + shapes match observed
```

All four are zero-side-effect (no file writes, no config touches). They are
the recommended way to validate skill health before/after edits.

## Known limitations (T7.8)

These are documented gaps that consumers should be aware of:

1. **`/v2/note` is undocumented in v2 swagger.** The skill uses it per
   `references/contract/notes-decision.md` (Decision A). Wrapper key is
   `notes`, body field per note is `content`. If Singularity API drops this
   endpoint, all derived tools (`task_full`, `project_tasks_full`,
   `inbox_list`) will return `status: "degraded"`.
2. **`task.note` is NOT embedded in `GET /v2/task/{id}` response.** The
   `expand=note` query parameter has no effect (verified empirically).
   Notes always require a separate `/v2/note` lookup.
3. **`inbox_list` uses paginated full scan with `page_limit=10` (10 000
   items max).** Filtering inbox tasks (no projectId) is client-side; the
   API has no server-side inbox filter. If you have >10k inbox tasks,
   the response will have `partial: true`.
4. **`rebuild_references` is N+1 for task groups.** One pagination call
   per project. ~1 minute for 50 projects, slower for larger accounts.
   Throttle between projects is not yet wired (paginator supports
   `throttle_ms` but rebuild loop doesn't pass it).
5. **Project lookup uses `references/projects.json` only.** Markdown cache is
   removed in v1.5.0.
6. **Legacy cache auto-migration is helper-only.** `cache.migrate_legacy_cache()`
   exists for JSON reference caches. `--verify-cache` will fail on legacy
   format until you run `rebuild_references`.
7. **Singularity API rate limits are not characterised.** Skill has
   built-in retry on 429 with exponential backoff (1s, 2s, 4s) and
   `iterate_pages(throttle_ms=...)` opt-in. No documented hard limit
   from the vendor; observed: bursty usage during `rebuild_references`
   has not triggered 429 on test account.

## Проверка готовности (при каждом вызове)

Перед выполнением любого запроса проверь наличие данных:

1. **`references/projects.json`** — если нет → запусти `rebuild_references()`
2. **`references/tags.json`** — если нет → запусти `rebuild_references()`
3. **`references/project_meta.json`** — legacy first-import fallback only; new project descriptions are edited with `project_describe`
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

## Project Lookup

Project lookup uses `references/projects.json` only. Markdown cache is removed
in v1.5.0.

Use `project_describe` to edit local project descriptions stored in
`references/projects.json`. `references/project_meta.json` is retained only as
a first-import fallback for brand new projects during `rebuild_references`.

## Migration handling

If a command returns `MIGRATION_PENDING`, read `source_path`, prepare a JSON
object keyed by project ID, call `project_describe` once with `batch`, then
rerun the original command. Do not edit `projects_cache.md`; it is archived by
the tool after a successful migration.

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

## Available Tools (<!-- TOOLS_COUNT_BEGIN -->64<!-- TOOLS_COUNT_END -->)

### Tasks (<!-- CATEGORY_TOOLS_COUNT_BEGIN:task -->11<!-- CATEGORY_TOOLS_COUNT_END:task --> tools)

<!-- CATEGORY_TOOLS_LIST_START:task -->
- `task_create` — Create task
- `task_delete` — Delete task
- `task_full` — Get task with its note (batch: task_get + note_list). Accepts task ID or Singularity URL.
- `task_get` — Get task by ID
- `task_group_create` — Create task group
- `task_group_delete` — Delete task group
- `task_group_get` — Get task group by ID
- `task_group_list` — List task groups
- `task_group_update` — Update task group
- `task_list` — List tasks
- `task_update` — Update task
<!-- CATEGORY_TOOLS_LIST_END:task -->

### Projects (<!-- CATEGORY_TOOLS_COUNT_BEGIN:project -->7<!-- CATEGORY_TOOLS_COUNT_END:project --> tools)

<!-- CATEGORY_TOOLS_LIST_START:project -->
- `project_create` — Create project
- `project_delete` — Delete project
- `project_describe` — Edit local project descriptions in references/projects.json
- `project_get` — Get project by ID
- `project_list` — List projects
- `project_tasks_full` — Get all tasks of a project with their notes (batch: task_list + note_list for all tasks)
- `project_update` — Update project
<!-- CATEGORY_TOOLS_LIST_END:project -->

### Tags (<!-- CATEGORY_TOOLS_COUNT_BEGIN:tag -->5<!-- CATEGORY_TOOLS_COUNT_END:tag --> tools)

<!-- CATEGORY_TOOLS_LIST_START:tag -->
- `tag_create` — Create tag
- `tag_delete` — Delete tag
- `tag_get` — Get tag by ID
- `tag_list` — List tags
- `tag_update` — Update tag
<!-- CATEGORY_TOOLS_LIST_END:tag -->

### Habits (<!-- CATEGORY_TOOLS_COUNT_BEGIN:habit -->10<!-- CATEGORY_TOOLS_COUNT_END:habit --> tools)

<!-- CATEGORY_TOOLS_LIST_START:habit -->
- `habit_create` — Create habit
- `habit_delete` — Delete habit
- `habit_get` — Get habit by ID
- `habit_list` — List habits
- `habit_progress_create` — Create habit progress entry
- `habit_progress_delete` — Delete habit progress entry
- `habit_progress_get` — Get habit progress entry by ID
- `habit_progress_list` — List habit progress entries
- `habit_progress_update` — Update habit progress entry
- `habit_update` — Update habit
<!-- CATEGORY_TOOLS_LIST_END:habit -->

### Kanban (<!-- CATEGORY_TOOLS_COUNT_BEGIN:kanban -->10<!-- CATEGORY_TOOLS_COUNT_END:kanban --> tools)

<!-- CATEGORY_TOOLS_LIST_START:kanban -->
- `kanban_status_create` — Create kanban status
- `kanban_status_delete` — Delete kanban status
- `kanban_status_get` — Get kanban status by ID
- `kanban_status_list` — List kanban statuses
- `kanban_status_update` — Update kanban status
- `kanban_task_status_create` — Create kanban task status
- `kanban_task_status_delete` — Delete kanban task status
- `kanban_task_status_get` — Get kanban task status by ID
- `kanban_task_status_list` — List kanban task statuses
- `kanban_task_status_update` — Update kanban task status
<!-- CATEGORY_TOOLS_LIST_END:kanban -->

### Notes (<!-- CATEGORY_TOOLS_COUNT_BEGIN:note -->5<!-- CATEGORY_TOOLS_COUNT_END:note --> tools)

<!-- CATEGORY_TOOLS_LIST_START:note -->
- `note_create` — Create note
- `note_delete` — Delete note
- `note_get` — Get note by ID
- `note_list` — List notes
- `note_update` — Update note
<!-- CATEGORY_TOOLS_LIST_END:note -->

### Time (<!-- CATEGORY_TOOLS_COUNT_BEGIN:time -->6<!-- CATEGORY_TOOLS_COUNT_END:time --> tools)

<!-- CATEGORY_TOOLS_LIST_START:time -->
- `time_stat_bulk_delete` — Bulk delete time tracking entries by filter
- `time_stat_create` — Create time tracking entry
- `time_stat_delete` — Delete time tracking entry
- `time_stat_get` — Get time tracking entry by ID
- `time_stat_list` — List time tracking entries
- `time_stat_update` — Update time tracking entry
<!-- CATEGORY_TOOLS_LIST_END:time -->

### Derived / Utility (<!-- CATEGORY_TOOLS_COUNT_BEGIN:derived -->10<!-- CATEGORY_TOOLS_COUNT_END:derived --> tools)

<!-- CATEGORY_TOOLS_LIST_START:derived -->
- `checklist_create` — Create checklist item
- `checklist_delete` — Delete checklist item
- `checklist_get` — Get checklist item by ID
- `checklist_list` — List checklist items
- `checklist_update` — Update checklist item
- `find_project` — Find project by name with auto-rebuild on cache miss
- `find_tag` — Find tag by name with auto-rebuild on cache miss
- `generate_meta_template` — Generate meta template file with _title fields for easy editing
- `inbox_list` — Get all tasks in Inbox (tasks without projectId). Returns up to 1000 tasks.
- `rebuild_references` — Regenerate references cache from API while preserving project descriptions in projects.json
<!-- CATEGORY_TOOLS_LIST_END:derived -->

## Справочники (references/)

Предгенерированные JSON-файлы для быстрого поиска UUID без API-вызовов.

| Файл | Содержимое | Обновление |
|------|------------|------------|
| `references/projects.json` | Все проекты: id, title, emoji, color, parent, isNotebook, archived, description | `rebuild_references()` |
| `references/tags.json` | Все теги: id, title, color, hotkey, parent, description | `rebuild_references()` |
| `references/task_groups.json` | Маппинг project_id → base_task_group_id для быстрого создания задач | `rebuild_references()` |
| `references/project_meta.json` | Legacy fallback descriptions for first import of brand new projects | Do not edit for normal updates; use `project_describe` |
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

### Project descriptions

Project descriptions live in `references/projects.json`. Edit them with
`project_describe`, using `id`+`text` for one project or `batch` for many.
`null` deletes a description; empty string is rejected unless
`allow_empty=true`.

### project_meta.json / tag_meta.json — legacy fallback

`project_meta.json` is no longer the normal editing surface for project
descriptions. It is used only once for a brand new project that is absent from
`references/projects.json` during `rebuild_references`. `tag_meta.json` keeps
the previous manual tag-description workflow.

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

При `rebuild_references()` existing project descriptions are preserved from
`references/projects.json`; `project_meta.json` is only a first-import fallback
for new project IDs. Tag descriptions still merge from `tag_meta.json`.

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
