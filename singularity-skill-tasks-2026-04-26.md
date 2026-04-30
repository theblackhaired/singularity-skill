# Атомарные задачи реализации singularity skill v2

Декомпозиция ТЗ из `singularity-skill-implementation-spec-2026-04-26.md` (v2).

**Формат задачи:**
- `ID` — уникальный идентификатор (`T<iter>.<n>`)
- `Title` — короткое имя
- `Files` — затрагиваемые файлы (новые или изменяемые)
- `Action` — что сделать одним предложением
- `Deps` — ID задач, которые должны быть выполнены ранее
- `Verify` — exact команда / условие приёмки
- `Estimate` — S (≤30 мин) / M (≤2 ч) / L (≤4 ч)

Каждая задача должна закрываться **одним коммитом** и быть верифицируемой автономно.

---

## Итерация 0 — Baseline и инфраструктура

### T0.1 — Probe-вызов /v2/note и фиксация observed shape
- Files: `references/contract/observed-api-shapes.json` (новый)
- Action: Сделать живой `GET /v2/note?containerId=<test_task_id>&maxCount=1`, записать observed JSON shape с redacted `token`/user content.
- Deps: —
- Verify: `test -f references/contract/observed-api-shapes.json && jq '.endpoints["/v2/note"]' references/contract/observed-api-shapes.json | grep -v null`
- Estimate: S

### T0.2 — Probe-вызов /v2/task/{id} с проверкой embedded note
- Files: `references/contract/observed-api-shapes.json`
- Action: Дополнить файл observed shape для `GET /v2/task/{id}` — присутствует ли поле `note` без `expand`, нужно ли `expand=note`.
- Deps: T0.1
- Verify: `jq '.endpoints["/v2/task/{id}"].note_field_presence' references/contract/observed-api-shapes.json | grep -E "always|with_expand|absent"`
- Estimate: S

### T0.3 — Notes API model decision (A/B/C)
- Files: `references/contract/notes-decision.md` (новый)
- Action: На основе T0.1+T0.2 выбрать одно: A (`/v2/note` undocumented), B (embedded `task.note`), C (`/v1/note`). Записать rationale.
- Deps: T0.1, T0.2
- Verify: `grep -E "^## Decision: [ABC]" references/contract/notes-decision.md`
- Estimate: S

### T0.4 — Catalog format decision
- Files: `references/contract/decisions.md` (новый)
- Action: Выбрать формат canonical catalog (catalog.py / catalog.json / typed structure), записать rationale.
- Deps: —
- Verify: `grep -E "^## Catalog format: " references/contract/decisions.md`
- Estimate: S

### T0.5 — JSON Schema draft decision
- Files: `references/contract/decisions.md`
- Action: Зафиксировать draft-07 (или иное) + reference validator (jsonschema lib).
- Deps: T0.4
- Verify: `grep -E "draft-07" references/contract/decisions.md`
- Estimate: S

### T0.6 — Semver scheme decision
- Files: `references/contract/decisions.md`
- Action: Зафиксировать semver правила: minor — additive поля derived tools, major — breaking, patch — internal.
- Deps: T0.4
- Verify: `grep -E "^## Versioning" references/contract/decisions.md`
- Estimate: S

### T0.7 — Contract baseline document
- Files: `references/contract/contract-baseline.md` (новый)
- Action: Зафиксировать canonical URL'ы (v2 primary `/v2/api-json`), список supported endpoints из swagger, список tools (63), текущий base_url.
- Deps: T0.1
- Verify: `grep -E "v2/api-json" references/contract/contract-baseline.md && grep -c "^- " references/contract/contract-baseline.md | awk '$1 >= 60'`
- Estimate: M

### T0.8 — Known drifts document
- Files: `references/contract/known-drifts.md` (новый)
- Action: Документировать расхождения documented vs observed: `/v2/note` отсутствует в swagger но используется кодом, дрейф counts (README=56/tools.json=60/SKILL=63/runtime=63), drift между двумя project caches.
- Deps: T0.7
- Verify: `wc -l references/contract/known-drifts.md | awk '$1 >= 20'`
- Estimate: S

### T0.9 — Secrets policy document
- Files: `references/contract/secrets-policy.md` (новый)
- Action: Записать: где хранится токен, .gitignore статус, правила redaction в snapshot artifacts, запрет переписывать config.json из cache layer, поведение --doctor без токена.
- Deps: —
- Verify: `grep -E "config\.json" references/contract/secrets-policy.md && grep -E "redact" references/contract/secrets-policy.md`
- Estimate: S

### T0.10 — CLI contract document
- Files: `references/contract/cli-contract.md` (новый)
- Action: Перечислить все invocations: `--list`, `--describe`, `--describe <tool>`, `--call <tool> --args ...`, `--refresh-cache`, `--doctor`. Для каждой — exit codes (0/1/2), формат stdout, формат stderr.
- Deps: —
- Verify: `grep -cE "^### " references/contract/cli-contract.md | awk '$1 >= 6'`
- Estimate: M

### T0.11 — Tests skeleton
- Files: `tests/__init__.py` (новый), `tests/conftest.py` (новый, минимальный), `requirements-dev.txt` (новый)
- Action: Создать пустой test runner skeleton + dev-deps файл (`jsonschema`, `pytest` опционально).
- Deps: —
- Verify: `python -m unittest discover tests -v 2>&1 | grep -E "Ran 0 tests|OK"`
- Estimate: S

### T0.12 — CLI parity skeleton (read-only snapshots)
- Files: `tests/test_cli_parity.py` (новый), `tests/snapshots/cli/list.txt`, `tests/snapshots/cli/describe.txt`
- Action: Написать тест, который запускает `python cli.py --list` и `python cli.py --describe`, сравнивает byte-identical со snapshot'ом. Снимки сгенерировать ОДИН РАЗ от текущего runtime.
- Deps: T0.11
- Verify: `python -m unittest tests.test_cli_parity -v; test $? -eq 0`
- Estimate: M

### T0.13 — Команда --doctor (skeleton, dry-run)
- Files: `cli.py`
- Action: Добавить argparse handler `--doctor`, который проверяет: config.json существует, base_url достижим, /v2/api-json возвращает OpenAPI, cache files читаемы. БЕЗ side-effects. БЕЗ перезаписи config.
- Deps: T0.9
- Verify: `python cli.py --doctor; test $? -eq 0` И `git diff config.json | wc -l` равно 0 после запуска
- Estimate: M

### T0.14 — Pre-iteration parity baseline check
- Files: —
- Action: Проверить что T0.12 snapshots — это canonical baseline текущего runtime (до любых правок). Зафиксировать commit-id baseline в `tests/README.md`.
- Deps: T0.12
- Verify: `grep -E "baseline commit:" tests/README.md`
- Estimate: S

---

## Итерация 1 — Note correctness hotfix

### T1.1 — Note resolver module (skeleton)
- Files: `note_resolver.py` (новый)
- Action: Создать модуль с функцией `resolve_note(client, container_id, container_type) -> dict` и константой `NoteStatus`. Реализация — заглушка возвращает `{"status": "unsupported"}`.
- Deps: T0.3
- Verify: `python -c "from note_resolver import resolve_note, NoteStatus"`
- Estimate: S

### T1.2 — Note resolver implementation согласно решению
- Files: `note_resolver.py`
- Action: Реализовать `resolve_note` согласно T0.3 (A/B/C). Покрыть капабилити-чек: shape валидация, fallback на `degraded`.
- Deps: T1.1
- Verify: `python -m unittest tests.test_note_resolver -v` (тесты в T1.6)
- Estimate: M

### T1.3 — Fix task_full
- Files: `cli.py`
- Action: Заменить inline note parsing в `_task_full_handler` (cli.py:1604-1611) на вызов `resolve_note()`. Добавить ответные поля `status`, `partial`, `note_status`, `warnings`.
- Deps: T1.2
- Verify: `grep -n 'note_list.get("content"' cli.py | wc -l` == 0 в области task_full
- Estimate: S

### T1.4 — Fix project_tasks_full (notes часть)
- Files: `cli.py`
- Action: Заменить inline note parsing в `_project_tasks_full_handler` (cli.py:1661-1663) на `resolve_note()`. Добавить мета-поля в ответ.
- Deps: T1.2
- Verify: `grep -A2 "_project_tasks_full_handler" cli.py | grep 'note_list.get("content"' | wc -l` == 0
- Estimate: S

### T1.5 — Fix inbox_list (notes часть)
- Files: `cli.py`
- Action: Заменить inline note parsing в `_inbox_list_handler` (cli.py:1705-1707) на `resolve_note()`. Добавить мета-поля.
- Deps: T1.2
- Verify: `grep -A2 "_inbox_list_handler" cli.py | grep 'note_list.get("content"' | wc -l` == 0
- Estimate: S

### T1.6 — URL injection fix в _task_full_handler
- Files: `cli.py`
- Action: Заменить `f"/v2/task/{task_id}"` (cli.py:1604) на `f"/v2/task/{urllib.parse.quote(task_id, safe='')}"`.
- Deps: —
- Verify: `grep -n 'f"/v2/task/{task_id}"' cli.py | wc -l` == 0
- Estimate: S

### T1.7 — Tests на note resolver (success/degraded/unsupported)
- Files: `tests/test_note_resolver.py` (новый), `tests/fixtures/note_responses.json` (новый)
- Action: Mocked unit tests на 3 пути: success extraction, degraded shape, unsupported endpoint.
- Deps: T1.2
- Verify: `python -m unittest tests.test_note_resolver -v; test $? -eq 0`
- Estimate: M

### T1.8 — CLI parity regen для derived tools
- Files: `tests/snapshots/cli/describe.txt` (regen)
- Action: Перегенерировать snapshot для `--describe task_full|project_tasks_full|inbox_list` так как у них теперь дополнительные мета-поля. Объяснить regen в commit message.
- Deps: T1.3, T1.4, T1.5
- Verify: `python -m unittest tests.test_cli_parity -v; test $? -eq 0`
- Estimate: S

### T1.9 — Bump skill version (minor)
- Files: catalog source (зависит от T0.4)
- Action: Bump skill version (e.g. `1.0.0` → `1.1.0`).
- Deps: T0.4
- Verify: `grep -E "version" <catalog source>` показывает новый minor
- Estimate: S

---

## Итерация 2 — Pagination + rate limiting

### T2.1 — Pagination helper module
- Files: `pagination.py` (новый)
- Action: Реализовать `iterate_pages(client, path, params, page_size=1000, max_pages=None) -> Iterator[dict]` через offset. Возвращает items, маркирует `truncated_at` при достижении `max_pages`.
- Deps: —
- Verify: `python -c "from pagination import iterate_pages"`
- Estimate: M

### T2.2 — Tests pagination (multi-page + truncation)
- Files: `tests/test_pagination.py` (новый), `tests/fixtures/paginated_responses.json`
- Action: Mock-tests: одна страница, две страницы, truncation при `max_pages=1`, пустой ответ.
- Deps: T2.1
- Verify: `python -m unittest tests.test_pagination -v; test $? -eq 0`
- Estimate: M

### T2.3 — Retry-After / rate-limit headers
- Files: `pagination.py`, опционально `cli.py` (`SingularityClient`)
- Action: Уважать `Retry-After` header в HTTP response 429; добавить opt-in `--throttle-ms` в paginator.
- Deps: T2.1
- Verify: `python -m unittest tests.test_pagination.TestRetryAfter -v`
- Estimate: M

### T2.4 — rebuild_references projects → paginator
- Files: `cli.py`
- Action: Заменить hardcoded `maxCount=1000` (cli.py:1174-1176) на `iterate_pages(...)`. При truncation пометить cache `complete: false`.
- Deps: T2.1
- Verify: `grep -n 'maxCount=1000' cli.py | grep -v "^# "` — не должно быть в rebuild_references
- Estimate: S

### T2.5 — rebuild_references tags → paginator
- Files: `cli.py`
- Action: То же что T2.4 для tags (cli.py:1185-1187).
- Deps: T2.1
- Verify: tags rebuild использует iterate_pages (grep)
- Estimate: S

### T2.6 — _refresh_project_cache → paginator
- Files: `cli.py`
- Action: Замена hardcoded в cli.py:1798.
- Deps: T2.1
- Verify: grep
- Estimate: S

### T2.7 — project_tasks_full → server-side projectId filter
- Files: `cli.py`
- Action: Заменить клиентскую фильтрацию (cli.py:1644) на server-side `params={"projectId": project_id}`. Использовать paginator.
- Deps: T2.1
- Verify: `grep -n 'all_tasks if t.get("projectId")' cli.py | wc -l` == 0
- Estimate: S

### T2.8 — inbox_list → paginator
- Files: `cli.py`
- Action: Замена в cli.py:1686. Добавить параметр `page_limit` (default 10). При достижении — `partial: true`.
- Deps: T2.1
- Verify: grep + test
- Estimate: M

### T2.9 — task_groups rebuild с throttling
- Files: `cli.py`
- Action: В цикле rebuild task_groups (cli.py:1292-1317) добавить `time.sleep(throttle_ms)` если задано.
- Deps: T2.3
- Verify: grep на `time.sleep` в task_groups loop
- Estimate: S

### T2.10 — Bump skill version
- Files: catalog source
- Action: Bump minor — semantic list tools поменялся (partial поле).
- Deps: T1.9
- Verify: version >= prev minor + 1
- Estimate: S

### T2.11 — CLI parity regen
- Files: `tests/snapshots/cli/`
- Action: Regen snapshots если изменился `--describe` для list-tools.
- Deps: T2.4..T2.8
- Verify: parity test passes
- Estimate: S

---

## Итерация 3 — Cache atomicity + secrets safety

### T3.1 — Atomic write helper
- Files: `io_utils.py` (новый) или `cache.py` если решено в T0.4
- Action: Функция `atomic_write_text(path, content)` через `tempfile.NamedTemporaryFile(dir=target_dir)` + `os.replace`.
- Deps: —
- Verify: `python -c "from io_utils import atomic_write_text"`
- Estimate: S

### T3.2 — Tests atomic write (interrupt simulation)
- Files: `tests/test_atomic_write.py`
- Action: Тест: запись прерывается до `replace` → старый файл сохранён.
- Deps: T3.1
- Verify: test passes
- Estimate: M

### T3.3 — Cache metadata format
- Files: `cache.py` (новый или часть существующего модуля)
- Action: Определить TypedDict / dataclass `CacheMeta` с полями: `generated_at`, `source_endpoint`, `page_size`, `pages_fetched`, `total_items`, `complete`, `schema_version`.
- Deps: —
- Verify: `python -c "from cache import CacheMeta"`
- Estimate: S

### T3.4 — projects.json через atomic_write + meta
- Files: `cli.py`
- Action: Замена `write_text` (cli.py:1249-1252) на atomic + добавление CacheMeta.
- Deps: T3.1, T3.3
- Verify: после rebuild `jq '.meta.complete' references/projects.json` равно `true`
- Estimate: S

### T3.5 — tags.json через atomic_write + meta
- Files: `cli.py`
- Action: Замена cli.py:1281-1284.
- Deps: T3.1, T3.3
- Verify: same pattern
- Estimate: S

### T3.6 — task_groups.json через atomic_write + meta
- Files: `cli.py`
- Action: Замена cli.py:1327-1330.
- Deps: T3.1, T3.3
- Verify: same
- Estimate: S

### T3.7 — *_meta.json через atomic_write
- Files: `cli.py`
- Action: Замена cli.py:1400-1401.
- Deps: T3.1
- Verify: same
- Estimate: S

### T3.8 — projects_cache.md через atomic_write
- Files: `cli.py`
- Action: Замена cli.py:1844.
- Deps: T3.1
- Verify: same
- Estimate: S

### T3.9 — Изоляция config.json от cache layer (КРИТИЧЕСКОЕ)
- Files: `cli.py`
- Action: Удалить запись config.json из `_check_and_refresh_cache` (cli.py:1849). Хранить last_refresh_timestamp в отдельном `cache_state.json` или вычислять из mtime cache files.
- Deps: T3.1
- Verify: `grep -n 'config_path.write_text\|config\.json.*write\|json\.dump.*config' cli.py | wc -l` == 0 (вне auth/config layer)
- Estimate: M

### T3.10 — Tests на race condition с config.json
- Files: `tests/test_config_safety.py`
- Action: Тест: запустить refresh, проверить что config.json не изменился (mtime + content).
- Deps: T3.9
- Verify: test passes
- Estimate: M

### T3.11 — Унификация двух project caches
- Files: `cli.py`, `projects_cache.md` (удалить или генерировать из projects.json)
- Action: Решить single source of truth. Либо удалить `projects_cache.md` и регенерировать on-demand из `references/projects.json`, либо наоборот.
- Deps: T3.4
- Verify: `test ! -f projects_cache.md || ! -f references/projects.json` (один из двух)
- Estimate: M

### T3.12 — TOCTOU fix в generate_meta_template
- Files: `cli.py`
- Action: Заменить exists-check + write (cli.py:1367, 1399-1401) на atomic create через `O_EXCL` flag.
- Deps: T3.1
- Verify: parallel-run test не падает с двойной записью
- Estimate: M

### T3.13 — Legacy cache migration
- Files: `cli.py` или `cache.py`
- Action: При первом запуске со старым cache (без `schema_version`) — переименовать в `*.legacy.json`, rebuild с нуля, warning в stderr.
- Deps: T3.3
- Verify: test с legacy cache fixture
- Estimate: M

### T3.14 — Команда --verify-cache
- Files: `cli.py`
- Action: Добавить argparse handler. Проверяет `complete: true`, `schema_version` совпадает, files читаемы.
- Deps: T3.3
- Verify: `python cli.py --verify-cache; test $? -eq 0` после успешного rebuild
- Estimate: M

### T3.15 — CLI parity check
- Files: —
- Action: Verify что parity tests всё ещё проходят.
- Deps: T3.4..T3.14
- Verify: `python -m unittest tests.test_cli_parity -v; test $? -eq 0`
- Estimate: S

---

## Итерация 4 — Metadata / schema normalization

### T4.1 — Canonical catalog source (новый формат)
- Files: `catalog.py` или `catalog.json` (по T0.4) — новый
- Action: Перенести содержимое `TOOL_CATALOG` (cli.py:395-1018) в canonical source. JSON Schema-style типы (`integer`, `string`, `array` с `items`, `object` с `properties`).
- Deps: T0.4, T0.5
- Verify: `python -c "from catalog import TOOL_CATALOG; assert len(TOOL_CATALOG) == 63"`
- Estimate: L

### T4.2 — `--list` использует canonical catalog
- Files: `cli.py`
- Action: Заменить hardcoded list на чтение из canonical catalog.
- Deps: T4.1
- Verify: `diff <(python cli.py --list | sort) <(jq -r '.[].name' tools.json | sort)` (после T4.5) — пусто
- Estimate: S

### T4.3 — `--describe` использует canonical catalog + draft-07
- Files: `cli.py`
- Action: Заменить cli.py:1933-1940 на genератор JSON Schema draft-07 с `items` для arrays, `properties` для objects.
- Deps: T4.1
- Verify: `python -c "import json,jsonschema,subprocess; jsonschema.Draft7Validator.check_schema(json.loads(subprocess.check_output(['python','cli.py','--describe','task_create'])))"`
- Estimate: M

### T4.4 — Регенератор tools.json
- Files: `scripts/regen_metadata.py` (новый)
- Action: Скрипт читает canonical catalog → пишет tools.json (содержит все 63 tools, включая derived).
- Deps: T4.1
- Verify: `python scripts/regen_metadata.py && jq 'length' tools.json` == 63
- Estimate: M

### T4.5 — tools.json regen
- Files: `tools.json`
- Action: Запустить T4.4 → коммитнуть результат.
- Deps: T4.4
- Verify: `jq 'length' tools.json` == 63 + `jq -r '.[].name' tools.json | grep -E "task_full|project_tasks_full|inbox_list"` присутствует
- Estimate: S

### T4.6 — Регенератор docs (counts, tool list)
- Files: `scripts/regen_metadata.py`, `README.md`, `SKILL.md`
- Action: Расширить скрипт чтобы он заменял placeholder'ы (`<!-- TOOLS_COUNT -->`, `<!-- TOOLS_LIST -->`) в README/SKILL.md.
- Deps: T4.4
- Verify: `grep -c "63" README.md` соответствует ожидаемому (через placeholder)
- Estimate: M

### T4.7 — Команда --verify-metadata
- Files: `cli.py`
- Action: Handler проверяет: tools.json совпадает с runtime catalog, README/SKILL соответствуют (через regen + diff).
- Deps: T4.4
- Verify: `python cli.py --verify-metadata; test $? -eq 0`
- Estimate: M

### T4.8 — Schema validation tests
- Files: `tests/test_schema.py`
- Action: Прогнать `--describe` для всех 63 tools через `jsonschema.Draft7Validator.check_schema`.
- Deps: T4.3
- Verify: `python -m unittest tests.test_schema -v; test $? -eq 0`
- Estimate: M

### T4.9 — Удалить ручные счётчики из SKILL.md
- Files: `SKILL.md`
- Action: Заменить хардкоженные "5 tools / 6 tools / 4 tools" (SKILL.md:108-228) на placeholder'ы.
- Deps: T4.6
- Verify: `grep -E "[0-9]+ tools" SKILL.md` — только в placeholder'ах
- Estimate: S

### T4.10 — Bump skill version (minor — schema формат поменялся)
- Files: catalog source
- Action: Bump.
- Deps: T2.10
- Verify: version
- Estimate: S

### T4.11 — CLI parity regen (--describe изменился)
- Files: `tests/snapshots/cli/describe.txt`
- Action: Regen snapshots — `--describe` теперь даёт valid JSON Schema. Объяснить в commit message.
- Deps: T4.3
- Verify: parity passes
- Estimate: S

---

## Итерация 5 — CLI parity + mocked contract tests (defensive layer)

### T5.1 — Полный --describe snapshot для всех 63 tools
- Files: `tests/snapshots/cli/describe_<tool>.txt` (63 файла)
- Action: Для каждого tool — отдельный snapshot файл `python cli.py --describe <tool>`.
- Deps: T4.3
- Verify: `find tests/snapshots/cli -name "describe_*.txt" | wc -l` == 63
- Estimate: M

### T5.2 — Расширенный test_cli_parity
- Files: `tests/test_cli_parity.py`
- Action: Параметризованный тест по 63 tools + общий `--list` + `--describe`.
- Deps: T5.1
- Verify: `python -m unittest tests.test_cli_parity -v` показывает >=63 tests
- Estimate: M

### T5.3 — Mocked HTTP server fixture
- Files: `tests/conftest.py`, `tests/fixtures/http_responses/`
- Action: Фикстура поднимает `http.server.HTTPServer` на random port, отвечает заранее заготовленным JSON.
- Deps: T0.11
- Verify: `python -m unittest tests.test_contract.TestFixture -v`
- Estimate: M

### T5.4 — Contract tests: SingularityClient
- Files: `tests/test_contract.py`
- Action: Тесты на get/post/patch/delete + retry + timeout против mocked server.
- Deps: T5.3
- Verify: tests pass
- Estimate: M

### T5.5 — Contract tests: derived tools (smoke)
- Files: `tests/test_contract.py`
- Action: Запустить task_full, project_tasks_full, inbox_list против mocked server. Проверить наличие всех мета-полей.
- Deps: T5.3, T1.7
- Verify: tests pass
- Estimate: M

### T5.6 — Cache tests: full lifecycle
- Files: `tests/test_cache.py`
- Action: Написать (build), прервать (interrupt), recover, migrate legacy. Проверить что config.json не тронут.
- Deps: T3.10, T3.13
- Verify: tests pass
- Estimate: M

### T5.7 — tests/README.md с copy-paste командами
- Files: `tests/README.md`
- Action: Для каждой итерации — секция с командами verification.
- Deps: T5.2..T5.6
- Verify: `grep -cE "^## Итерация" tests/README.md` >= 8
- Estimate: M

---

## Итерация 6 — Modular refactor

### T6.1 — Извлечь client.py (HTTP transport)
- Files: `client.py` (новый), `cli.py`
- Action: Перенести `SingularityClient` (cli.py:32-127) в `client.py`. В cli.py — `from client import SingularityClient`.
- Deps: T5.2
- Verify: `python -m unittest tests.test_cli_parity -v; test $? -eq 0`
- Estimate: M

### T6.2 — Извлечь errors.py
- Files: `errors.py` (новый)
- Action: Определить typed exceptions (`SingularityError`, `RateLimitError`, `NotFoundError` и т.п.).
- Deps: —
- Verify: `python -c "from errors import SingularityError"`
- Estimate: S

### T6.3 — Извлечь config.py
- Files: `config.py` (новый), `cli.py`
- Action: Перенести config loader (cli.py:134-139). Это **ЕДИНСТВЕННОЕ** место, читающее `config.json`.
- Deps: T3.9
- Verify: `grep -rn "config\.json" --include="*.py" .` показывает только в config.py + tests
- Estimate: S

### T6.4 — Извлечь resources.py
- Files: `resources.py` (новый)
- Action: Перенести `RESOURCES` (cli.py:149-297).
- Deps: —
- Verify: `python -c "from resources import RESOURCES"`
- Estimate: S

### T6.5 — Извлечь crud.py
- Files: `crud.py` (новый)
- Action: Перенести generic CRUD handlers (cli.py:304-388).
- Deps: T6.1, T6.4
- Verify: parity passes
- Estimate: M

### T6.6 — Catalog source финализирован
- Files: `catalog.py` или `catalog.json`
- Action: Завершить миграцию из T4.1 — все импорты идут из canonical.
- Deps: T4.1
- Verify: `grep "TOOL_CATALOG = " cli.py | wc -l` == 0
- Estimate: M

### T6.7 — Извлечь cache.py
- Files: `cache.py` (новый)
- Action: Перенести cache loaders + rebuild + atomic write helpers (cli.py:1065-1345, 1733-1875).
- Deps: T6.1, T6.3
- Verify: parity passes
- Estimate: L

### T6.8 — Извлечь derived.py
- Files: `derived.py` (новый)
- Action: Перенести `task_full`, `project_tasks_full`, `inbox_list`, `find_project`, `find_tag` (cli.py:1411-1718).
- Deps: T6.1, T6.5, T6.7, T1.2 (note_resolver уже отдельный модуль)
- Verify: parity passes
- Estimate: L

### T6.9 — Извлечь doctor.py
- Files: `doctor.py` (новый)
- Action: Перенести `--doctor` логику.
- Deps: T0.13, T6.1, T6.7
- Verify: `python cli.py --doctor; test $? -eq 0`
- Estimate: M

### T6.10 — main.py + cli.py compat wrapper
- Files: `main.py` (новый), `cli.py`
- Action: `main.py` — entrypoint с argparse и dispatch. `cli.py` остаётся как thin compatibility shim (`from main import main; if __name__ == "__main__": main()`).
- Deps: T6.1..T6.9
- Verify: `wc -l cli.py | awk '$1 < 50'` (тонкий shim) и `python cli.py --list` работает
- Estimate: M

### T6.11 — Проверка отсутствия циклических импортов
- Files: —
- Action: Прогнать `python -c "import main, client, catalog, cache, crud, derived, doctor, config, errors, pagination, note_resolver"`.
- Deps: T6.10
- Verify: команда выше exit 0
- Estimate: S

### T6.12 — Final parity check
- Files: —
- Action: Гарантировать что snapshot diff = пусто.
- Deps: T6.10
- Verify: `python -m unittest discover tests -v; test $? -eq 0`
- Estimate: S

### T6.13 — Bump skill version (patch — internal refactor)
- Files: catalog source
- Action: patch bump.
- Deps: T6.10
- Verify: version
- Estimate: S

---

## Итерация 7 — Final hardening

### T7.1 — Команда --verify-api
- Files: `doctor.py` (или `cli.py`)
- Action: Read-only smoke против live API. Проверяет что endpoints отвечают, response shape соответствует observed-api-shapes.json.
- Deps: T6.9
- Verify: `python cli.py --verify-api; test $? -eq 0` (с валидным token)
- Estimate: M

### T7.2 — Команда --doctor агрегирует verify-*
- Files: `doctor.py`
- Action: `--doctor` запускает `--verify-cache`, `--verify-metadata`, `--verify-api` и агрегирует результат.
- Deps: T7.1, T3.14, T4.7
- Verify: `python cli.py --doctor; test $? -eq 0`
- Estimate: M

### T7.3 — Закрыть silent except — место 1
- Files: соответствующий модуль (после рефактора)
- Action: cli.py:1202-1203 → конкретный exception + log.
- Deps: T6.10
- Verify: grep
- Estimate: S

### T7.4 — Закрыть silent except — место 2
- Files: соответствующий модуль
- Action: cli.py:1212-1213.
- Deps: T6.10
- Verify: grep
- Estimate: S

### T7.5 — Закрыть silent except — место 3
- Files: соответствующий модуль
- Action: cli.py:1384-1385.
- Deps: T6.10
- Verify: grep
- Estimate: S

### T7.6 — Закрыть silent except — место 4
- Files: соответствующий модуль
- Action: cli.py:1437.
- Deps: T6.10
- Verify: grep
- Estimate: S

### T7.7 — Закрыть silent except — места 5,6
- Files: соответствующий модуль
- Action: cli.py:1978-1979, 1985-1986.
- Deps: T6.10
- Verify: `grep -rn 'except Exception:\s*$\|except Exception:\s*pass' --include='*.py' .` == 0 в production
- Estimate: S

### T7.8 — Known limitations section в README/SKILL.md
- Files: `README.md`, `SKILL.md`
- Action: Перечислить: notes API model (выбранное A/B/C), inbox_list page_limit, что rebuild_references делает N+1 без параллелизма, etc.
- Deps: —
- Verify: `grep -E "^## Known limitations" SKILL.md`
- Estimate: M

### T7.9 — Snapshot tests на degraded behavior
- Files: `tests/test_degraded_paths.py`
- Action: Note unsupported, cache incomplete, partial inbox — все с явными snapshot'ами выходного JSON.
- Deps: T1.7, T3.6
- Verify: tests pass
- Estimate: M

### T7.10 — opt-in --integration-write режим
- Files: `cli.py`, `tests/test_integration.py`
- Action: Тесты против live API создающие/удаляющие test entities. Срабатывают только при `SINGULARITY_TEST_ACCOUNT=1`.
- Deps: T6.10
- Verify: `SINGULARITY_TEST_ACCOUNT=0 python -m unittest tests.test_integration` — skipped
- Estimate: L

---

## Итерация 8 — Backlog (опциональные мелкие фиксы)

### T8.1 — _request retry-loop guard
- Files: `client.py`
- Action: cli.py:64-113 (после рефактора — в client.py): добавить explicit `raise` после loop при `max_retries=0`.
- Deps: T6.1
- Verify: test на max_retries=0
- Estimate: S

### T8.2 — _load_indexed_projects defensive
- Files: `cache.py`
- Action: cli.py:1091 (после рефактора — cache.py): `pid = p.get("id"); if pid is None: skip + log`.
- Deps: T6.7
- Verify: test с битым cache fixture
- Estimate: S

### T8.3 — _check_and_refresh_cache переиспользует client
- Files: `cache.py`
- Action: cli.py:1749/1761/1773/1777: один `SingularityClient` на весь cache refresh.
- Deps: T6.7
- Verify: количество `SingularityClient(` в cache flow ≤ 1
- Estimate: S

### T8.4 — inbox_list filter precision
- Files: `derived.py`
- Action: cli.py:1690 (derived.py): заменить `not t.get("projectId")` на `t.get("projectId") in (None, "")`.
- Deps: T6.8
- Verify: unit test на edge-case `projectId == 0`
- Estimate: S

### T8.5 — task_groups base detection deterministic
- Files: `cache.py`
- Action: cli.py:1311: сортировать по `parentOrder` или иному стабильному ключу перед `[0]`.
- Deps: T6.7
- Verify: test
- Estimate: S

### T8.6 — CHANGELOG обновлён до 63 tools
- Files: `CHANGELOG.md`
- Action: Добавить entry с финальным count.
- Deps: T4.5
- Verify: `grep -E "63 tools" CHANGELOG.md`
- Estimate: S

### T8.7 — SKILL.md inbox_list документация обновлена
- Files: `SKILL.md`
- Action: SKILL.md:239 — заменить "up to 1000 tasks" на правильное описание (page_limit + partial).
- Deps: T2.8
- Verify: grep
- Estimate: S

---

## Сводная таблица зависимостей (top-level)

```
Итерация 0 (T0.*) — независима
  ↓
Итерация 1 (T1.*) — нужны T0.3, T0.4, T0.11, T0.12
  ↓
Итерация 2 (T2.*) — нужны T0.* (+ опционально T1.* для согласованности)
  ↓
Итерация 3 (T3.*) — нужны T2.* (atomic пишется поверх обновлённых rebuild flow'ов)
  ↓
Итерация 4 (T4.*) — нужны T0.4, T0.5
  ↓
Итерация 5 (T5.*) — нужны T1.*..T4.*
  ↓
Итерация 6 (T6.*) — нужны T5.* (parity tests как safety net)
  ↓
Итерация 7 (T7.*) — нужны T6.*
  ↓
Итерация 8 (T8.*) — нужны T6.* (rвые file paths после рефактора)
```

## Параллелизация

Внутри одной итерации эти задачи можно делать параллельно:
- **Итерация 0:** T0.4..T0.10 параллельно (decisions + docs); T0.1+T0.2+T0.3 — sequential.
- **Итерация 1:** T1.3, T1.4, T1.5, T1.6 — параллельно после T1.2.
- **Итерация 2:** T2.4..T2.9 — параллельно после T2.1.
- **Итерация 3:** T3.4..T3.8 — параллельно после T3.1+T3.3.
- **Итерация 4:** T4.4 (regen скрипт) последовательно после T4.1; tools.json/SKILL.md/README — параллельно через regen.
- **Итерация 6:** T6.2, T6.3, T6.4 — параллельно (нет cross-deps); T6.5..T6.9 — sequential.
- **Итерация 7:** T7.3..T7.7 — параллельно (разные функции).
- **Итерация 8:** все параллельно.

## Метрики

- Всего задач: **96**
- Estimate: ~25 S + ~50 M + ~5 L = ориентировочно 130-150 человеко-часов
- Критический путь (sequential): T0.1 → T0.3 → T1.2 → T2.1 → T3.1 → T4.1 → T5.1 → T6.10 → T7.2 ≈ 30 ч
