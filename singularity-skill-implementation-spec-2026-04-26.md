# ТЗ: стабилизация и переработка skill `singularity`

> **Версия 2 (2026-04-26).** Учтены результаты ревью: подтверждены claims против кода (file:line), исправлен порядок итераций (тесты до рефактора), добавлены пропущенные слои (auth/secrets, error handling, rate limiting), зафиксированы решения, которые раньше принимались поздно (notes API model, catalog format, JSON Schema draft, CLI contract).

## 1. Мета

**Объект работ**
`C:\Users\kirill.gorosov\.claude\skills\singularity`

**Текущий статус**
`reviewed v2 / not fixed`

**Основание для работ**
По итогам ревью, подтверждённого против кода (cli.py 2013 строк), выявлены:
- поломка note-related derived tools — все три derived tool читают `note_list.get("content", [])`, что не соответствует ни v2 OpenAPI (там notes — embedded поле в task/project), ни observed runtime;
- неверная стратегия выборки задач и кэшей — hardcoded `maxCount=1000` в шести местах, клиентская фильтрация вместо server-side `projectId`;
- дрейф `README` (56) / `SKILL.md` (63) / `tools.json` (60) / runtime (63);
- невалидный `--describe` schema output (Python-имена типов вместо JSON Schema);
- архитектурная перегрузка одного `cli.py` (13 переплетённых слоёв);
- отсутствие any verification beyond `py_compile`;
- небезопасное обращение с auth-токеном (хранение в `config.json` + перезапись на каждом auto-refresh).

**Цель**
Сделать skill предсказуемым, проверяемым и пригодным для дальнейшего ревью и сопровождения без скрытого дрейфа API и metadata, и без silent корректности.

**Ключевой результат**
После завершения всех итераций:
- documented CRUD по подтверждённому API работает корректно;
- derived tools либо работают корректно, либо явно возвращают degraded/unsupported;
- кэши не теряют данные тихо и не затирают пользовательский токен;
- metadata генерируются из одного источника истины;
- есть reviewable набор тестов и self-check сценариев;
- любой рефактор защищён CLI parity tests;
- secrets и auth явно отделены от транспорта.

**Формат выполнения**
Итерационный. Каждая итерация должна быть merge/review-friendly и иметь собственные acceptance criteria.

**Жёсткие ограничения**
- Не делать write-операции в live API в smoke checks по умолчанию (mocked write — допустим в deterministic tests; opt-in `--integration-write` против тестового аккаунта — отдельный режим).
- Не оставлять silent fallback, который маскирует неполный результат как корректный.
- Не хранить вручную счётчики tools в нескольких местах (к концу всех итераций).
- Не завязывать корректность бизнес-логики на кэш.
- **Не писать токен / secrets в snapshot artifacts** (`observed-api-shapes.json` и любые fixtures).
- **Не использовать "просто переименовать поле" как fix для notes** — нужно сначала зафиксировать модель API.
- **Не делать рефактор раньше, чем появится CLI parity baseline.**

## 2. Границы работ

### In scope
- `cli.py`
- `README.md`
- `SKILL.md`
- `tools.json`
- `config.json` (только в части secrets handling: документирование и защита от перезаписи)
- новые test/spec/helper файлы при необходимости
- новая команда self-check / doctor
- refactor структуры skill при сохранении CLI-совместимости

### Out of scope
- добавление новых бизнес-фич Singularity API сверх текущего набора tools
- write-side migration пользовательских данных
- переход на внешние runtime-зависимости вместо stdlib (test/dev-зависимости — допустимы, см. §3.1)
- автоматическое исправление данных в аккаунте Singularity
- замена самого формата хранения config.json на keyring/OS secret store

### Test-only dependencies (allowed)
Несмотря на stdlib-only для runtime, для test harness разрешены dev-зависимости с фиксацией в `requirements-dev.txt`:
- `pytest` или `unittest` (последний — stdlib)
- `jsonschema` (для валидации `--describe` против meta-schema)
- `responses` / `pytest-httpserver` или ручной `http.server` mock (для contract tests без сети)

## 3. Общие требования к каждой итерации

Для каждой итерации обязательно:
- отдельный reviewable diff;
- обновлённые acceptance criteria;
- список затронутых файлов;
- тесты или smoke-check доказательства;
- явный список known limitations, если остались;
- обновление docs, если поменялся runtime behavior;
- **прохождение CLI parity test suite** (после Итерации 0).

Каждая итерация должна содержать:
- `Problem`
- `Scope`
- `Non-goals`
- `Changes`
- `Artifacts`
- `Acceptance criteria`
- `Verification commands` (новое — exact команды, доказывающие выполнение)
- `Review checklist`
- `Risks`

### 3.1 Версии и стандарты, фиксируемые один раз
- **JSON Schema:** `draft-07` (максимальная совместимость; reference validator — `jsonschema` lib в dev-deps).
- **Python:** 3.11+ (как в текущем runtime).
- **Atomic write на Windows:** `os.replace()` поверх `tempfile.NamedTemporaryFile` в той же директории; читатели не должны держать file handle на target во время replace.
- **Skill versioning:** semver. Bump в каждой итерации, которая меняет внешний contract derived tools (минимум — Итерации 1, 4).

## 4. Итерация 0: Baseline, контракт и инфраструктура

### Problem
Сейчас нет зафиксированного baseline контракта: какие endpoints реально считаются supported, какие response shapes observed, какой CLI-контракт защищаем при будущем рефакторе, как хранятся secrets, есть ли test runner.

### Scope
- Зафиксировать contract baseline для текущего skill (API + CLI).
- Добавить machine-readable источник observed API facts.
- Зафиксировать архитектурные решения, которые иначе будут pинимать поздно (catalog format, JSON Schema draft, notes model).
- Создать минимальный test runner skeleton.
- Подготовить основу для всех следующих итераций.

### Non-goals
- Не чинить production logic.
- Не делать большой refactor.
- Не писать tests на содержание (только runner skeleton + CLI parity baseline).

### Changes
- Создать `references/contract/` (или `docs/contract/`) с артефактами baseline.
- Зафиксировать:
  - canonical API docs URLs;
  - observed response shapes (в `observed-api-shapes.json` с redacted токеном);
  - список supported endpoints;
  - список drift/zones of uncertainty;
  - **secrets handling policy** (см. ниже).
- Решить и записать, **где живут заметки** (см. §4.1 ниже).
- Решить и записать **canonical catalog format** (`catalog.py` vs `catalog.json` vs typed structure) с rationale.
- Решить и записать **JSON Schema draft** (рекомендация: draft-07).
- Создать `cli-contract.md` со списком всех invocations и ожидаемых exit codes / output (см. §4.2).
- Создать `tests/__init__.py` + `tests/test_cli_parity.py` (skeleton; позже заполняется).
- Добавить `--doctor` dry-run команду (read-only, без write):
  - проверка config.json существует и не записан в git;
  - проверка base_url достижим;
  - проверка `/v2/api-json` возвращает OpenAPI;
  - проверка cache files читаемы;
  - **БЕЗ side-effects.**

### 4.1 Notes API model decision (новое требование)

В swagger расхождение, которое ТЗ v1 не учитывало:

| URL | Версия | Notes |
|---|---|---|
| `https://api.singularity-app.com/v2/api-json` | OpenAPI 3.0 v2 | Standalone `/v2/note` отсутствует. Notes — embedded поле `note` (Delta) в `Task` и `Project`. |
| `https://api.singularity-app.com/api-json` | OpenAPI v1 | Полноценный `/v1/note` CRUD, response — `NoteResponseDto` с полем `content`. |

При этом `cli.py:1604-1611` реально вызывает `/v2/note` (не задокументированный в v2) и читает `content` (которого там нет, но есть в v1). То есть код в текущем виде — кентавр между v1 и v2.

**Acceptance Итерации 0 (notes-specific):**
- Сделать живой probe-вызов `/v2/note` с записью observed response shape в `observed-api-shapes.json` (с redacted токеном и redacted user content).
- Зафиксировать одно из решений в `notes-decision.md`:
  - **A.** `/v2/note` существует undocumented и используется как сейчас → задокументировать observed shape, в Итерации 1 фиксить parsing под него.
  - **B.** `/v2/note` не работает или возвращает мусор → в Итерации 1 переписать derived tools на чтение embedded `task.note` через `GET /v2/task/{id}` (canonical v2 way).
  - **C.** Использовать `/v1/note` явно → задокументировать как осознанное использование v1 endpoint, добавить в `known-drifts.md`.

Без этого решения Итерация 1 заблокирована.

### 4.2 CLI parity baseline (новое требование)

`cli-contract.md` обязан содержать:
- Полный список invocations: `--list`, `--describe`, `--describe <tool>`, `--call <tool> --args ...`, `--refresh-cache`, `--doctor`.
- Для каждой invocation: ожидаемый exit code (0/1/2), формат stdout (plain text / JSON), формат stderr.
- Snapshot byte-identical output для read-only invocations (`--list`, `--describe` без аргументов) — фиксируется в `tests/snapshots/cli/`.
- Список tools (имена, не описания) — golden file для проверки drift.

`tests/test_cli_parity.py` запускает все read-only invocations и сравнивает с snapshot'ами.

### 4.3 Secrets handling policy (новое требование)

В `secrets-policy.md` зафиксировать:
- Где хранится токен сейчас (`config.json` рядом с кодом).
- Как он попадает в repo: `.gitignore` уже исключает (проверить и явно подтвердить).
- Правило: **никакая итерация не пишет токен в snapshot artifacts**. Все fixture файлы либо не содержат токен, либо содержат placeholder `<REDACTED>`.
- Правило: `_check_and_refresh_cache` **не должен переписывать `config.json`** (см. cli.py:1849 — текущая race-condition уязвимость, фикс в Итерации 3).
- Правило: при отсутствии токена `--doctor` возвращает структурированную ошибку, не падает.

### Artifacts
- `references/contract/contract-baseline.md`
- `references/contract/observed-api-shapes.json` (redacted)
- `references/contract/known-drifts.md`
- `references/contract/notes-decision.md`
- `references/contract/cli-contract.md`
- `references/contract/secrets-policy.md`
- `references/contract/decisions.md` (catalog format, JSON Schema draft, semver scheme)
- `tests/__init__.py`, `tests/test_cli_parity.py` (skeleton + read-only snapshots)
- `requirements-dev.txt`
- `--doctor` команда

### Acceptance criteria
- Есть отдельный артефакт с documented vs observed.
- Проверка `--doctor` выполняется без write-запросов и без побочных эффектов на cache/config.
- В артефактах явно указано:
  - canonical v2: `https://api.singularity-app.com/v2/api-json`
  - v1 (use only if explicitly chosen for notes): `https://api.singularity-app.com/api-json`
  - `https://api.singularity-app.com/api-json` не использовать как primary v2 source.
- `notes-decision.md` содержит одно из решений A/B/C с rationale.
- `cli-contract.md` существует и `tests/test_cli_parity.py` проходит для всех read-only invocations.
- `decisions.md` содержит выбор формата catalog (catalog.py / catalog.json / typed) и JSON Schema draft.
- В `observed-api-shapes.json` нет реального токена и нет реального user content (только структура).

### Verification commands
```bash
python cli.py --doctor; test $? -eq 0
python -m unittest tests.test_cli_parity -v; test $? -eq 0
test -f references/contract/notes-decision.md
test -f references/contract/cli-contract.md
test -f references/contract/decisions.md
grep -L "$(jq -r .token < config.json)" references/contract/observed-api-shapes.json  # нет токена
```

### Review checklist
- Не смешаны documented facts и inference.
- Все observed statements воспроизводимы.
- Нет скрытых live write side effects.
- В snapshot artifacts отсутствует токен.

### Risks
- Возможен drift API между baseline и следующими итерациями.
- Если probe `/v2/note` показывает unstable behavior — решение B (использовать embedded `task.note`) увеличивает scope Итерации 1.

## 5. Итерация 1: Hotfix корректности note-related tools

### Problem
`task_full` ([cli.py:1608-1611](cli.py:1608)), `project_tasks_full` ([cli.py:1661-1663](cli.py:1661)), `inbox_list` ([cli.py:1705-1707](cli.py:1705)) ненадёжны и возвращают ложнопустые заметки. Все три читают `note_list.get("content", [])`, что не соответствует ни v2 OpenAPI, ни выбранной в Итерации 0 модели.

Дополнительно [cli.py:1604](cli.py:1604) вызывает API без `urllib.parse.quote(task_id)` — URL injection.

### Scope
- Реализовать notes-resolver согласно решению A/B/C из `notes-decision.md`.
- Ввести explicit degraded behavior.
- Не допускать silent wrong success.
- Закрыть URL injection через quote().

### Non-goals
- Не решать весь рефактор skill.
- Не переписывать все handlers.
- Не менять CLI contract (новые мета-поля в response — additive, см. §5.1).

### Changes
- Вынести note resolution в отдельный helper/module (`note_resolver`).
- Реализация резолвера зависит от решения Итерации 0:
  - **A:** parsing observed shape `/v2/note`.
  - **B:** читать `task.note` из `GET /v2/task/{id}` напрямую, никаких `/v2/note` вызовов.
  - **C:** через `/v1/note` с полем `content`.
- Перед использованием note endpoint проверять capability:
  - endpoint reachable;
  - response shape соответствует observed-api-shapes.json;
  - filtering behavior подтверждён.
- Если capability не подтверждён — derived tools возвращают structured degradation status.
- Закрыть URL injection в [cli.py:1604](cli.py:1604) через `urllib.parse.quote(task_id, safe='')`.

### 5.1 Формат расширения derived tools (additive contract)
Derived tools расширяются полями:
- `status: "ok" | "degraded" | "unsupported"`
- `partial: bool`
- `note_status: "ok" | "missing" | "skipped" | "error"`
- `warnings: list[str]`

**Старые поля (`note`, `tasks`, и т.п.) сохраняются с прежним semantic.** Consumers, игнорирующие новые поля, не ломаются. Это закрепляется в `cli-contract.md` и проверяется в parity tests.

### Artifacts
- `note_resolver.py` (или соответствующий модуль)
- обновлённые derived tools
- `tests/test_note_resolver.py` (mocked contract tests на success/degraded/unsupported режимы)
- semver bump (minor: добавили optional поля)

### Acceptance criteria
- Нет чтения `note_list.get("content", [])`.
- Для success path заметка реально извлекается из shape, зафиксированной в `observed-api-shapes.json`.
- Для uncertain path tool возвращает `status: "degraded"` с конкретным `warnings`, а не пустой результат.
- Документация updated.
- URL injection в task_id закрыт.
- CLI parity tests проходят (старые consumers не сломаны).

### Verification commands
```bash
python -m unittest tests.test_note_resolver -v
python -m unittest tests.test_cli_parity -v
grep -n 'note_list.get("content"' cli.py | wc -l   # должно быть 0
grep -n '"/v2/task/" + task_id\|f"/v2/task/{task_id}"' cli.py  # должно быть в quote()
```

### Review checklist
- Нигде не осталось implicit assumption, что note response field = `content`.
- Нет silent swallowing ошибок note layer.
- Новый формат ответов additive — старые поля присутствуют.
- task_id экранирован.

### Risks
- Если решение B выбрано — может оказаться что embedded `task.note` приходит только при `expand=note`, что меняет API-контракт `task_get`. Документировать в `known-drifts.md`.

## 6. Итерация 2: Пагинация, server-side фильтр, rate limiting

### Problem
- List-операции и rebuild logic режут данные по hardcoded `maxCount=1000` в шести местах: [cli.py:1174](cli.py:1174), [1185](cli.py:1185), [1630](cli.py:1630), [1640](cli.py:1640), [1686](cli.py:1686), [1798](cli.py:1798). При >1000 записей — silent truncation.
- `project_tasks_full` ([cli.py:1644](cli.py:1644)) делает клиентскую фильтрацию вместо server-side `projectId`, хотя RESOURCES["task"] этот фильтр поддерживает (cli.py:186).
- `task_groups` rebuild делает N+1 запросов без задержек ([cli.py:1292-1317](cli.py:1292)) — риск 429 на больших аккаунтах.
- Нет уважения `Retry-After` / rate-limit headers.

### Scope
- Ввести единый paginator.
- Исправить list-стратегию для derived tools и rebuild cache.
- Устранить silent truncation.
- Добавить базовый rate limiting.

### Non-goals
- Не делать крупный модульный refactor beyond extraction of shared pagination helper.
- Не менять бизнес-смысл tools.

### Changes
- Добавить общий `iterate_pages(client, path, params, page_size=1000, max_pages=None)` — итеративный обход через `offset`.
- Перевести на него:
  - `rebuild_references` (projects, tags)
  - `_refresh_project_cache`
  - `project_tasks_full`
  - `inbox_list`
  - все остальные места с hardcoded `maxCount=1000`.
- `project_tasks_full` перевести на `projectId` server-side filter.
- Для inbox использовать paginated full scan с явным `page_limit` параметром (default 10 страниц = 10k items); при превышении — `partial: true`.
- Любой неполный обход явно маркируется:
  - `partial: true`
  - `warnings: ["truncated at N items"]`
  - `fetched_pages`, `fetched_items`
- Paginator уважает `Retry-After` header (если есть) и имеет opt-in `--throttle-ms` параметр (default 0).
- task_groups rebuild ограничивает concurrency (последовательный обход с `time.sleep(throttle_ms)` если задано).

### Artifacts
- `pagination.py` helper
- обновлённые list/rebuild handlers
- `tests/test_pagination.py` (mocked multi-page responses + truncation behavior + Retry-After)
- docs о semantics `partial`

### Acceptance criteria
- Нет critical paths, зависящих от одного `maxCount=1000`.
- `project_tasks_full` использует server-side `projectId` filter primary path.
- При неполной выборке tool не возвращает "успешный полный" результат — `partial: true` + `warnings`.
- Smoke-check на mocked responses доказывает корректность multi-page.
- Rate limiting не падает на 429, использует `Retry-After`.

### Verification commands
```bash
python -m unittest tests.test_pagination -v
grep -n 'maxCount=1000\|"maxCount": 1000' cli.py | wc -l   # должно быть 0 (только в pagination.py с явным комментарием)
grep -n 'all_tasks if t.get("projectId")' cli.py | wc -l   # 0
python -m unittest tests.test_cli_parity -v
```

### Review checklist
- Нет дублированной pagination logic по коду.
- Все list handlers обрабатывают пустые/неожиданные поля явно.
- Нигде не потеряны query filters при переходе на paginator.
- Нет N+1 без throttling.

### Risks
- Изменение semantics list tools.
- Нужен аккуратный review response aggregation.

## 7. Итерация 3: Кэш как индекс, atomic write, secrets safety

### Problem
- Кэш сейчас может быть неполным и при этом выглядеть валидным.
- Rebuild и refresh пишут файлы без atomic discipline — [cli.py:1249](cli.py:1249), [1281](cli.py:1281), [1327](cli.py:1327), [1400](cli.py:1400), [1844](cli.py:1844), [1849](cli.py:1849).
- **Критическая race-condition:** `_check_and_refresh_cache` ([cli.py:1849](cli.py:1849)) переписывает `config.json` (с токеном) при каждом auto-refresh. Concurrent runner может затереть свежий токен старым snapshot'ом.
- Два независимых кэша проектов с разными TTL: `references/projects.json` (TTL=30 дней) и `projects_cache.md` (TTL=7 дней) — silent drift.
- TOCTOU между `generate_meta_template` exists-check и записью.

### Scope
- Переписать lifecycle кэшей.
- Сделать cache completeness observable.
- Убрать silent corruption/partial overwrite.
- **Изолировать config.json от cache lifecycle.**
- Унифицировать два кэша projects.

### Non-goals
- Не внедрять внешнюю БД или сложное storage layer.
- Не менять формат хранения secrets (это отдельная задача за scope).

### Changes
- Ввести cache metadata:
  - `generated_at`
  - `source_endpoint`
  - `page_size`
  - `pages_fetched`
  - `total_items`
  - `complete: bool`
  - `schema_version: int`
- Писать кэш через `tempfile.NamedTemporaryFile(dir=target_dir)` + `os.replace()`.
- Если rebuild failed midway — старый кэш сохраняется; новый incomplete не публикуется как canonical, либо публикуется с `complete: false`.
- `find_project` / `find_tag` учитывают cache state (`complete: false` → warning).
- **`_check_and_refresh_cache` НЕ пишет config.json.** Логика auto-refresh-timestamp выносится либо в отдельный `cache_state.json`, либо перестаёт перситентно храниться (rebuild по TTL без запоминания last_run в config).
- Убрать дублирующийся `projects_cache.md` (или унифицировать с `references/projects.json` как single source).
- Закрыть TOCTOU в `generate_meta_template` через atomic `O_EXCL` или явную блокировку.
- Migration: при первом запуске со старым кэшем (без `schema_version`) — auto-detect, переименовать в `*.legacy.json`, rebuild с нуля; warning в stdout.

### Artifacts
- новый cache metadata format
- atomic write helper в `cache.py` или `io_utils.py`
- cache verification output (`--verify-cache` команда)
- migration note в `CHANGELOG.md`
- `tests/test_cache.py` (atomic write under interrupt, partial cache marking, legacy migration)

### Acceptance criteria
- Нельзя получить "здоровый" кэш без `complete=true` или явной деградации.
- При ошибке rebuild старые usable cache files не теряются.
- По metadata можно понять, полон ли кэш и из чего собран.
- **Концurrent runner не теряет токен из config.json.**
- Только один кэш проектов (либо JSON, либо MD; не оба).
- `--verify-cache` падает если `complete: false` или `schema_version` устарел.

### Verification commands
```bash
python -m unittest tests.test_cache -v
python cli.py --verify-cache; test $? -eq 0
grep -n 'config_path.write_text\|config\.json.*write' cli.py | wc -l   # 0 — config не переписывается из cache layer
test ! -f projects_cache.md || ! -f references/projects.json   # один кэш, не два
python -m unittest tests.test_cli_parity -v
```

### Review checklist
- Нет частично записанных canonical cache files.
- Tool behavior не зависит от неявного наличия старых полей.
- Нормально обрабатывается legacy cache format (auto-migration).
- Никакой код вне auth/config layer не пишет config.json.

### Risks
- Переход на новый cache format может затронуть обратную совместимость.
- Унификация двух кэшей projects может потребовать миграции для пользователей с custom workflows вокруг `projects_cache.md`.

## 8. Итерация 4: Нормализация metadata и schema

### Problem
- `README` (56), `SKILL.md` (63), `tools.json` (60) и runtime catalog (63) расходятся.
- `tools.json` не содержит derived tools (`task_full`, `project_tasks_full`, `inbox_list`).
- `--describe` ([cli.py:1933-1940](cli.py:1933)) генерирует невалидную JSON Schema: использует Python-имена типов (`int`, `str`, `list`, `object`) вместо `integer`, `string`, `array`, `object`. Нет `items` для arrays, нет `properties` для objects.
- Ручные счётчики "5 tools / 6 tools / 4 tools" хардкожены в SKILL.md:108-228.
- CHANGELOG отстаёт (`58 → 60` при реальных 63).

### Scope
- Сделать один source of truth для tool catalog (формат зафиксирован в Итерации 0).
- Привести schema к валидному JSON Schema draft-07.
- Убрать ручной drift docs/counts.

### Non-goals
- Не менять названия tools без необходимости.
- Не изобретать собственный schema format.

### Changes
- Реализовать canonical catalog source согласно решению из `decisions.md` (catalog.py / catalog.json / typed).
- Из canonical source генерировать:
  - `tools.json`
  - `--list` output
  - `--describe` output
  - tool section в docs (через generator script)
  - tool count в README/SKILL.md (placeholder + generator)
- Привести типы к JSON Schema draft-07:
  - `int` → `integer`
  - `str` → `string`
  - `float` → `number`
  - `bool` → `boolean`
  - `list` → `array` (с обязательным `items`)
  - `object` → `object` (с минимальным `properties`)
- Для массивов и объектов добавить минимальное описание структуры (хотя бы `items: {"type": ...}`).
- Добавить verify step `--verify-metadata`, который падает при drift.
- Validate `--describe` против JSON Schema draft-07 meta-schema через `jsonschema` lib (dev-deps).
- Semver bump (minor: schema формат изменился).

### Artifacts
- canonical tool catalog
- generator/update script (`scripts/regen_metadata.py`)
- regenerated `tools.json` (включая derived tools)
- updated docs (с auto-generated tool listing и count)
- `tests/test_schema.py` (validation против meta-schema)
- `--verify-metadata` команда

### Acceptance criteria
- `tools.json` совпадает с runtime catalog.
- В docs нет ручных чисел про count tools (только placeholder + auto-fill).
- `--describe` выдаёт schema, валидную против JSON Schema draft-07 meta-schema.
- Есть тест/проверка на drift (`--verify-metadata`).
- `tools.json` содержит все 63 runtime tools, включая derived.

### Verification commands
```bash
python cli.py --verify-metadata; test $? -eq 0
python -m unittest tests.test_schema -v
python -c "import json,jsonschema; jsonschema.Draft7Validator.check_schema(json.loads(__import__('subprocess').check_output(['python','cli.py','--describe','task_create'])))"
diff <(python cli.py --list | sort) <(jq -r '.[].name' tools.json | sort)   # должен быть пустым
grep -c 'tools' README.md   # никаких хардкодных "63 tools" — только template tag
python -m unittest tests.test_cli_parity -v
```

### Review checklist
- Нигде не осталось legacy `str/int/float/list/object` как external schema types.
- `tools.json` содержит все runtime tools, включая derived.
- README и SKILL.md generated или частично generated predictably.

### Risks
- Возможно, придётся слегка менять формат docs.
- Если generator будет слишком хрупким, это добавит новый класс проблем — закрыть тестом на самой generator script.

## 9. Итерация 5: CLI parity tests и mocked contract tests (defensive layer)

> **Эта итерация была "Итерацией 6" в v1 ТЗ — частично перенесена сюда, ДО рефактора.**

### Problem
Сейчас skill почти не имеет воспроизводимой верификации. Делать рефактор монолита (Итерация 6) без тестов = ломать CLI без safety net.

### Scope
- Добавить полноценный mocked contract test layer.
- Зафиксировать byte-identical baseline для всех read-only invocations.
- Подготовить инструменты для безопасного рефактора.

### Non-goals
- Не строить CI-инфраструктуру.
- Не добавлять live e2e write tests по умолчанию.
- Snapshot tests для нового behavior — следующая итерация (после refactor).

### Changes
- Расширить `tests/test_cli_parity.py` из Итерации 0 до полного покрытия:
  - `--list` snapshot
  - `--describe` snapshot для всех 63 tools
  - `--describe` без аргумента
  - `--call <tool> --args <noop>` для read-only tools (с mocked HTTP)
- Добавить `tests/test_contract.py` — mocked contract tests для каждого слоя:
  - HTTP transport (`SingularityClient.get/post/patch/delete`)
  - pagination
  - cache load/save
  - note resolver
  - derived tools
- Добавить `tests/conftest.py` с фикстурой mocked HTTP-сервера (через `http.server` или `pytest-httpserver`).

### Artifacts
- `tests/test_cli_parity.py` (полный)
- `tests/test_contract.py`
- `tests/conftest.py`, `tests/fixtures/`
- `tests/snapshots/cli/`
- `tests/README.md` с copy-paste командами для reviewer

### Acceptance criteria
- Все 63 tools покрыты `--describe` snapshot test'ами.
- Все read-only invocations имеют byte-identical baseline.
- Mocked contract tests покрывают: pagination edge cases, cache atomic write, note resolver A/B/C, derived tools degraded path.
- Test suite запускается одной командой и не делает сетевых вызовов.
- Reviewer может воспроизвести каждый claim через единичную команду из `tests/README.md`.

### Verification commands
```bash
python -m unittest discover tests -v; test $? -eq 0
python -m unittest tests.test_cli_parity tests.test_contract -v
test "$(find tests/snapshots/cli -name '*.txt' | wc -l)" -ge 63
```

### Review checklist
- Тесты проверяют observed risks, а не только happy path.
- Нет сетевой нестабильности в unit/snapshot tests.
- Live-check отделён от deterministic tests.

### Risks
- Если parity tests слишком строгие — каждое legitimate улучшение output потребует regenerate snapshots. Документировать процесс regen в `tests/README.md`.

## 10. Итерация 6: Модульный refactor под защитой parity tests

> **Эта итерация была "Итерацией 5" в v1 ТЗ — перенумерована, идёт ПОСЛЕ тестов.**

### Problem
Один `cli.py` (2013 строк) совмещает 13 ответственностей: HTTP transport, RESOURCES schema, generic CRUD, TOOL_CATALOG, dispatch, indexed cache loaders, references rebuild, meta template generator, find_project/find_tag, derived batch tools, auto-refresh cache lifecycle, argparse CLI, config.

### Scope
- Разделить код на модули.
- Сохранить внешний CLI-контракт (проверяется parity tests из Итерации 5).
- Упростить дальнейший review.

### Non-goals
- Не делать функциональную революцию.
- Не ломать существующие команды.

### Target structure
- `main.py` — entrypoint (thin)
- `cli.py` — argparse + compat wrapper (для существующих invocation patterns)
- `client.py` — HTTP transport, retry, timeout
- `errors.py` — typed exceptions
- `config.py` — config + secrets loading (изолированно от всего)
- `catalog.py` или `catalog.json` — tool metadata (по решению Итерации 0)
- `resources.py` — RESOURCES schema (data layer)
- `crud.py` — generic CRUD handlers
- `pagination.py` — paginator (создан в Итерации 2)
- `note_resolver.py` — notes layer (создан в Итерации 1)
- `cache.py` — refresh/rebuild/index helpers
- `derived.py` — composed tools
- `doctor.py` — self-check / verify-* commands
- `tests/` — unit/contract/snapshot tests

### Changes
- Перенести код по ответственности.
- Ввести небольшой internal API между модулями.
- Сохранить `python cli.py --list/--describe/--call` совместимость через thin wrapper.
- Никаких циклических зависимостей: derived → (catalog, client, cache, note_resolver), но НЕ обратно.
- Side effects (HTTP вызовы, cache writes) изолированы в client.py / cache.py.

### Artifacts
- новая файловая структура
- compat wrapper в `cli.py`
- updated import graph
- diagrams / docs опционально

### Acceptance criteria
- **Все CLI parity tests из Итерации 5 проходят без изменения snapshot'ов.**
- Внешние команды не ломаются (byte-identical output для read-only).
- `cli.py` становится thin entry wrapper или compatibility shim.
- Review локализуем по модулям, а не по огромному монолитному diff.
- Нет циклических зависимостей (`python -c "import main; ..."` + проверка через `pydeps` или ручную ревизию).

### Verification commands
```bash
python -m unittest tests.test_cli_parity -v   # MUST pass без regen snapshot'ов
python -m unittest discover tests -v
python -c "import ast,sys; [ast.parse(open(f).read()) for f in ['main.py','client.py','catalog.py','cache.py','derived.py','doctor.py']]"
wc -l cli.py   # должен быть значительно меньше 2013
```

### Review checklist
- Нет циклических зависимостей.
- Side effects изолированы.
- Derived tools не тащат внутрь себя transport/cache details напрямую.
- config.py — единственное место, читающее `config.json`.

### Risks
- Самая большая итерация по диффу.
- Без parity tests из Итерации 5 эта итерация невыполнима безопасно.

## 11. Итерация 7: Дополнительная test/ops обвязка

> **Финальная hardening итерация. Бывшая часть "Итерации 6" v1, после рефактора.**

### Problem
После рефактора нужно добавить операционные команды и тесты на новые behaviors, которые не вошли в parity baseline.

### Scope
- Добавить final verification commands.
- Добавить раздел Known limitations в docs.
- Закрыть оставшиеся silent failures.

### Non-goals
- Не строить тяжёлый CI-фреймворк, если skill локальный.
- Не добавлять e2e write tests по умолчанию.

### Changes
- Добавить:
  - snapshot tests на новый behavior (degraded responses, partial cache, etc.)
  - schema validation tests расширенные
  - non-write smoke checks
- Расширить команды:
  - `--doctor` — aggregate всех проверок
  - `--verify-api` — read-only API smoke
  - `--verify-cache` — cache integrity
  - `--verify-metadata` — drift между catalog и tools.json
- Документировать expected output этих команд.
- Добавить раздел `Known limitations` в README/SKILL.md.
- Закрыть silent `except Exception: pass` в [cli.py:1202](cli.py:1202), [1212](cli.py:1212), [1384](cli.py:1384), [1437](cli.py:1437), [1978](cli.py:1978), [1985](cli.py:1985) — логировать или возвращать структурированную ошибку.
- Добавить optional `--integration-write` режим (env var `SINGULARITY_TEST_ACCOUNT=1`, вне default DoD).

### Artifacts
- расширенные `tests/`
- `testdata/` fixtures
- verification commands (полный набор)
- docs for operators/reviewers
- `Known limitations` секция

### Acceptance criteria
- Минимальный repeatable test suite покрывает все итерации.
- `--doctor` агрегирует все verify-* checks.
- Reviewer может воспроизвести ключевые claims без чтения всего кода (через `tests/README.md`).
- Нет silent `except: pass` в production коде (только в test fixtures).

### Verification commands
```bash
python cli.py --doctor; test $? -eq 0
python cli.py --verify-api; test $? -eq 0
python cli.py --verify-cache; test $? -eq 0
python cli.py --verify-metadata; test $? -eq 0
python -m unittest discover tests -v; test $? -eq 0
grep -rn 'except Exception:\s*$\|except Exception:\s*pass' --include='*.py' .   # 0 в production
```

### Review checklist
- Тесты проверяют observed risks, а не только happy path.
- Нет сетевой нестабильности в unit/snapshot tests.
- Live-check отделён от deterministic tests.
- Все silent except закрыты.

### Risks
- При плохом разделении live и mock tests suite станет хрупким.
- Нужно жёстко держать deterministic layer отдельно.

## 12. Итерация 8 (опциональная): Дополнительные находки кода

> **Не вошли в основные итерации, но требуют решения. Может быть выполнена параллельно с любой итерацией ≥3, либо отнесена в backlog.**

Список конкретных file:line из ревью:

1. **`_request` retry-loop** ([cli.py:64-113](cli.py:64)) — при `max_retries=0` есть путь возврата `None` без явного `raise`. Закрыть guard.
2. **`_load_indexed_projects`** ([cli.py:1091](cli.py:1091)) — `pid = p["id"]` без обработки `KeyError`. Один битый объект = краш всего find_project. Использовать `.get()` + skip с warning.
3. **`_check_and_refresh_cache` создаёт `SingularityClient` 3-4 раза** ([cli.py:1749](cli.py:1749), [1761](cli.py:1761), [1773](cli.py:1773), [1777](cli.py:1777)). После Итерации 6 — переиспользовать единый client.
4. **`_inbox_list_handler`** ([cli.py:1690](cli.py:1690)) — filter `not t.get("projectId")` зацепит `""` и `0`. Использовать `t.get("projectId") in (None,)` или явную проверку.
5. **`base_tg = task_groups[0]`** ([cli.py:1311](cli.py:1311)) — без сортировки по `parentOrder`. "Base" task group = недетерминированный.
6. **CHANGELOG** — bump до 63 tools после Итерации 4.
7. **Documented `inbox_list ... up to 1000 tasks`** ([SKILL.md:239](SKILL.md:239)) — обновить после Итерации 2.

## 13. Порядок выполнения (исправленный)

```
Итерация 0  — baseline + decisions + cli-contract + test runner skeleton
Итерация 1  — note correctness hotfix (с реальной API model)
Итерация 2  — pagination + rate limiting
Итерация 3  — cache atomicity + secrets safety
Итерация 4  — metadata/schema normalization
Итерация 5  — CLI parity + mocked contract tests (DEFENSIVE LAYER)
Итерация 6  — modular refactor (под защитой parity tests)
Итерация 7  — final hardening + verify-* commands + Known limitations
Итерация 8  — опциональные мелкие фиксы (backlog)
```

Причина:
- сначала зафиксировать контракт и инфраструктуру (включая решения, которые иначе принимаются поздно);
- потом убрать ложную корректность;
- потом чинить полноту данных;
- потом нормализовать packaging;
- **потом построить тесты, которые защитят рефактор**;
- только после этого безопасно делать крупный refactor.

## 14. Общий Definition of Done (измеримый)

Работа считается завершённой, если **каждый пункт verifiable командой**:

| # | Критерий | Команда верификации |
|---|---|---|
| 1 | derived tools не возвращают заведомо ложные ответы | `python -m unittest tests.test_note_resolver -v` (degraded path test) |
| 2 | нет silent truncation на list/cache paths | `python -m unittest tests.test_pagination tests.test_cache -v` |
| 3 | metadata runtime/docs/schema синхронизированы | `python cli.py --verify-metadata; test $? -eq 0` |
| 4 | canonical API source для v2 зафиксирован | `test -f references/contract/contract-baseline.md && grep -q 'v2/api-json' references/contract/contract-baseline.md` |
| 5 | drift-зоны явно обозначены | `test -f references/contract/known-drifts.md` |
| 6 | есть self-check и repeatable verification | `python cli.py --doctor; test $? -eq 0` |
| 7 | кодовая база skill разбита по ответственностям | `wc -l cli.py` < 300 (compat wrapper); все модули из Итерации 6 существуют |
| 8 | reviewer может проверить каждую итерацию отдельно | `test -f tests/README.md && grep -c '^## Итерация' tests/README.md` ≥ 8 |
| 9 | secrets не утекают в snapshot artifacts | `grep -rL "<actual_token>" references/contract/ tests/fixtures/` |
| 10 | `--describe` валидирована против JSON Schema draft-07 | `python -m unittest tests.test_schema -v` |

## 15. Формат итогового ревью по каждой итерации

### Review Template
- `Verdict`: `APPROVED` / `NEEDS CHANGE`
- `Scope matched`: yes/no
- `Acceptance criteria met`: yes/no (с указанием verification commands и их exit codes)
- `New regressions`: list (CLI parity tests должны это ловить)
- `Residual risks`: list
- `Docs updated`: yes/no
- `Tests/evidence`: list (test files + результаты)
- `Follow-up moved to next iteration`: list (limit: ≤ 3 items; всё сверх — в Итерацию 8 / backlog)

## 16. Что считать блокером на ревью

Блокер, если:
- tool продолжает молча врать о заметках;
- partial result выглядит как complete;
- metadata всё ещё имеют несколько источников правды;
- schema невалидна против JSON Schema draft-07;
- refactor ломает CLI parity tests (snapshot diff не объяснён);
- self-check делает write-запросы;
- docs не отражают новый runtime behavior;
- **token попадает в snapshot artifacts;**
- **`config.json` переписывается из cache layer;**
- **итерация N зависит от инфраструктуры из итерации N+k без явной cross-reference.**

## 17. История изменений ТЗ

- **v1 (initial)** — первая редакция от Codex.
- **v2 (2026-04-26)** — после ревью:
  - Все 6 claims подтверждены против кода с file:line.
  - Перенумерован порядок: тесты (CLI parity + mocked contract) теперь Итерация 5, ДО рефактора (бывшая Итерация 5 → Итерация 6).
  - Расширена Итерация 0: notes API model decision (A/B/C), CLI contract, secrets policy, JSON Schema draft, catalog format, test runner skeleton.
  - Добавлена секция secrets handling — закрытие race-condition с перезаписью `config.json` при auto-refresh кэша.
  - Добавлено rate limiting в Итерацию 2.
  - DoD переписан в измеримом формате с verification commands.
  - Добавлена Итерация 8 (backlog) с конкретными file:line из ревью кода.
