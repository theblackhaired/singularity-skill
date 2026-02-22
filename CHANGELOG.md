# Changelog

## [2026-02-22] — Batch tools for task + note retrieval

### Added - Batch operations
- Новый инструмент `task_full` — получить задачу с заметкой одним запросом
- Поддержка парсинга Singularity URLs (singularityapp:// и https://web.singularity-app.com/)
- Новый инструмент `project_tasks_full` — получить все задачи проекта с заметками
- Фильтрация по project_id на клиенте (API не поддерживает параметр project_id)
- Опциональный флаг `include_notes` для отключения загрузки заметок
- Tool counter: 60 → 62 tools

**Цель:** Уменьшить количество API запросов при работе с задачами и заметками

## [2026-02-22] — Performance optimizations (indexing + task_groups cache)

### Added - Task groups cache
- Кэширование task_groups для быстрого создания задач
- Файл `references/task_groups.json` с маппингом `project_id → base_task_group_id`
- При создании задачи не нужен API запрос `task_group_list` (~1800ms экономии)
- `find_project` теперь возвращает `task_group_id` для найденных проектов
- Auto-rebuild task_groups при обновлении кэша (с прогрессом в stderr)

### Added - Indexed cache search
- Helper функции `_load_indexed_projects()` и `_load_indexed_tags()` для O(1) поиска
- Индексы: `by_id`, `by_title_lower`, `by_parent` для быстрого доступа
- Exact match в `find_project`/`find_tag` теперь O(1) вместо O(n)
- Partial match остаётся O(n), но с оптимизированной итерацией

### Changed - Retry mechanism
- **Уже был реализован ранее** — добавлен в документацию для полноты
- HTTP ошибки 429, 500, 502, 503, 504 с exponential backoff
- URLError (timeout, connection refused) тоже обрабатываются
- Логи retry в stderr

**Цель:** Ускорение работы скилла + стабильность при проблемах с сетью

## [2026-02-22] — Cache-first documentation

### Changed — Documentation improvements
- Добавлена секция "⚡ ПРАВИЛО ПРИОРИТЕТА КЭША" с явным указанием использовать кэш вместо API
- Таблица сравнения: что НЕ делать vs что ДЕЛАТЬ
- Обновлён Quick Router с примерами использования кэша
- Добавлен пример фильтрации подпроектов через кэш (вместо `project_list`)
- Явное указание когда использовать API (только write operations и динамические данные)

**Цель:** Предотвратить ненужные API запросы когда данные уже есть в кэше

## [2026-02-22] — Auto-refresh cache with TTL

### Added - Auto-refresh cache with TTL
- Автоматическая проверка возраста кэша при каждом вызове скилла
- Параметр `cache_ttl_days` в config.json (по умолчанию 30 дней)
- Кэш обновляется автоматически если отсутствует или старше TTL
- ISO timestamp в `projects.json` и `tags.json` (поле `generated`)
- Логи обновления в stderr

### Added - Cache-miss search tools
- Новый инструмент `find_project` — поиск проекта по имени с автообновлением кэша при промахе
- Новый инструмент `find_tag` — поиск тега по имени с автообновлением кэша при промахе
- Case-insensitive partial match по умолчанию, опция `exact=true` для точного совпадения
- Автоматический rebuild cache при отсутствии результата
- Логи rebuild в stderr
- Обновлён счётчик: 58 → 60 tools

## [2026-02-20] — Reference cache system

### Added — Reference cache system
- New tool `rebuild_references` — generates JSON cache files from Singularity API
- `references/projects.json` — all projects with fields: id, title, emoji, color, parent, isNotebook, archived, description
- `references/tags.json` — all tags with fields: id, title, color, hotkey, parent, description
- `references/project_meta.json` — manual project descriptions (role, purpose), merged into projects.json during rebuild
- `references/tag_meta.json` — manual tag descriptions, merged into tags.json during rebuild
- `projects.json` and `tags.json` now include `description` field from corresponding meta files (null if not defined)

### Added — Meta template generator
- New tool `generate_meta_template` — generates template meta file with `_title` fields for all projects/tags
- Support for service fields with `_` prefix in meta files (ignored during merge, used for editing convenience)
- `_title` field in project_meta.json and tag_meta.json for visual UUID identification during manual editing

### Added — Startup readiness check & initialization workflow
- `SKILL.md`: readiness check — verifies 4 required files on every skill invocation, auto-initializes missing data
- `SKILL.md`: documentation for reference system — how to use, when to update, description rules
- `SKILL.md`: note about what `task_get` and `note_get` return (note, tags, deadline are returned; subtasks are not, use separate `task_list`)

### Added — Metadata guidelines
- `SKILL.md`: rules for generating `description` for projects — explain project purpose, main tasks/goals, 1 line, Russian language
- `SKILL.md`: rules for generating `description` for tags — tag purpose, brief description

### Changed
- Tool counter updated: 56 → 58 tools
- Skill version: 1.0.0 → 1.1.0
- Quick Router expanded: added lines for UUID lookup (projects/tags), rebuild_references, and generate_meta_template

### Technical
- `.gitignore`: added `references/*.json` and `!references/*.example.json` to protect personal data
- Created example files for git: `projects.example.json`, `tags.example.json`, `project_meta.example.json`, `tag_meta.example.json`

## [Initial Release] — Version 1.0.0

### Added
- Direct REST API v2 client for Singularity App
- 56 tools for task, project, habit, and note management
- Bearer token authorization via config.json
- Project cache in projects_cache.md with auto-update every 7 days
- Python stdlib only (urllib, json, ssl) — no external dependencies
- Read-only mode for safe usage
