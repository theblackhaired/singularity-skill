# Changelog

## [1.5.0] - 2026-04-28

- Removed markdown project-cache runtime paths: no `--refresh-cache`, no auto-generation of `projects_cache.md`; project lookup now uses `references/projects.json` only.
- Added `project_describe` for local project descriptions with single/batch modes, dry-run, CAS via `base_sha256`, atomic batch validation, and structured error responses.
- Added description migration state in `references/projects.json` and idempotent archive of `projects_cache.md` after successful migration.
- Updated `rebuild_references` to preserve existing JSON descriptions and use `project_meta.json` only as a one-time fallback for brand new project IDs.
- Fixed `cache_ttl_days: null` handling and surfaced corrupt JSON caches as structured `CACHE_CORRUPT` errors.
- Regenerated `tools.json`, `SKILL.md` tool lists, and describe snapshots for 64 runtime tools.

### Stage 2 — module split

- Created `crud.py` for generated CRUD handlers and `time_stat_bulk_delete`.
- Created `derived.py` for derived lookup, full-task, project-task, and inbox handlers.
- Extended `cache.py` with `rebuild_references`, cache refresh, description migration/archive flow, and SHA-256/CAS helpers.
- Kept `main()` in `cli.py`; extracting `main.py` would currently require importing `TOOL_CATALOG` and `TOOL_DISPATCH` back from `cli.py`, creating a circular import.

## [1.4.2] - 2026-04-28

- Fix array parameter item types in generated JSON schemas (`note_create`/`note_update` content as objects, `task.notifies` as integers).
- Fixed `rebuild_references` completeness metadata: projects, tags, and task-group caches now all write `_meta.complete=false` whenever any paginated fetch returns partial data or task-group fetch errors occur.
- Fixed `find_project` and `find_tag` reads from incomplete caches: partial data is still served, but responses now include `degraded=true` and `reason="cache incomplete"`.

## [2026-04-26] — v1.4.0: Spec-driven stabilization (Iter 0–4 + 7 + 8 partial)

Реализация плана из `singularity-skill-implementation-spec-2026-04-26.md` (после Codex-ревью). 5 итераций закрыты в течение одного дня, ~60 атомарных задач из 96.

### Iter 0 — Baseline & infrastructure
- `references/contract/` — 7 артефактов: `observed-api-shapes.json` (redacted), `notes-decision.md` (Decision A), `decisions.md`, `secrets-policy.md`, `cli-contract.md`, `contract-baseline.md`, `known-drifts.md`.
- `tests/` — runner skeleton, parity baseline (`test_cli_parity.py` 4 tests).
- Новая команда `--doctor` — 8 read-only sanity checks, zero side effects.

### Iter 1 — Note correctness hotfix (1.0.0 → 1.1.0)
- **CRITICAL fix**: `note_list.get("content")` → `note_list.get("notes")` в 3 derived handlers. Заметки теперь реально извлекаются (раньше всегда `null`).
- Новый модуль `note_resolver.py` (Decision A, capability check).
- URL injection fix в `_task_full_handler`: `quote(task_id, safe='')`.
- Derived tools возвращают additive metadata: `status`, `partial`, `note_status`, `warnings`, `raw`.
- 12 unit tests для note_resolver.

### Iter 2 — Pagination & rate limiting (1.1.0 → 1.2.0)
- Новый модуль `pagination.py` — `iterate_pages()` с offset+maxCount, max_pages truncation, wrapper key autodetect, `throttle_ms`, hard_page_cap=10000.
- 6 hardcoded `maxCount=1000` сайтов заменены на paginator.
- `project_tasks_full` теперь использует **server-side `projectId` filter** (раньше client-side scan).
- `inbox_list` paginated full scan с `page_limit=10` (10k items max).
- task_groups rebuild сортирует по `parentOrder` (детерминированный base).
- 15 pagination tests.

### Iter 3 — Cache atomicity & secrets safety (1.2.0)
- Новый модуль `cache.py` — `atomic_write_text/json`, `CacheMeta` (schema_version=1), `wrap_cache`, `read_cache`, `migrate_legacy_cache`, `parse_html_timestamp_comment`.
- Все 5 cache-write сайтов через atomic temp+os.replace.
- **SECURITY: T3.9** — cache layer больше **не пишет config.json** (race condition с токеном закрыта). 4 теста-guard.
- TOCTOU fix в `generate_meta_template` через `os.O_EXCL`.
- Новая команда `--verify-cache` — детектит legacy/incomplete/missing.

### Iter 4 — Metadata & schema (1.2.0 → 1.4.0)
- **`--describe` валидна как JSON Schema draft-07** для всех 63 tools (`int→integer`, `str→string`, `list→array+items`, `object→object+properties`, `$schema` reference).
- `scripts/regen_metadata.py` — single source of truth = runtime `TOOL_CATALOG`. tools.json регенерируется (60 → 63 entries, derived включены).
- Новая команда `--verify-metadata` — exit 1 на drift.
- 9 schema tests (jsonschema.Draft7Validator на 63 tools + tools.json sync).

### Iter 7 — Final hardening (partial)
- Новая команда `--verify-api` — read-only live smoke 6 endpoints.
- **SECURITY**: token redaction в error bodies (truncate 500 + regex `Bearer\s+\S+ → ***`).
- "Known limitations" секция в SKILL.md.
- 4 silent `except Exception: pass` site закрыты с stderr-логированием.

### Iter 8 — Backlog (partial)
- T8.1: `_request` retry-loop guard против silent None return на `max_retries=0`.
- T8.2: `_load_indexed_projects` defensive — пропускает entries без `id` со stderr-warning.
- T8.5: task_groups сортировка по `parentOrder` (детерминированный base task group).

### Tests
- **66 tests** in 4 suites: parity (4) + note_resolver (12) + config_safety (4) + pagination (15) + cache (22) + schema (9). All passing.

### Cross-review
- **Code review (Opus)**: APPROVED WITH NITS (0 BLOCKER, 0 MAJOR, 6 MINOR).
- **Security review (Opus)**: PASS WITH NOTES (0 CRITICAL, 0 HIGH, 1 MEDIUM closed, 3 LOW).
- 4 Codex agents участвовали в работе (docs, tests, regen).

### Known drifts (deferred)
- **Drift 7**: `projects_cache.md` + `references/projects.json` сосуществуют (разные TTL). Унификация — следующая итерация.
- **T3.13**: legacy cache auto-migration в cli.py wiring (helper готов).
- **Iter 6 (modular refactor)**: `cli.py` (~2400 LOC) пока монолит; `errors.py` + `config.py` извлечены, остальные модули — следующая итерация под защитой parity tests.

### Tool counter
60 → 63 (derived: `task_full`, `project_tasks_full`, `inbox_list` теперь в tools.json).

---

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
