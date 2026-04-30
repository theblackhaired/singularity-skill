# Known Drifts (T0.8)

### Drift 1: `/v2/note` undocumented

- What is documented: `v2/api-json` does not document `/v2/note`; v1 documents a note wrapper with `content`.
- What is observed in runtime: `GET /v2/note?containerId=<id>&maxCount=1` returns 200 with wrapper key `notes`; each item has its own `content` field.
- Where in code: `cli.py:198-204` defines `/v2/note`; `cli.py:1608-1610`, `cli.py:1661-1663`, and `cli.py:1705-1707` call `/v2/note` but read wrapper key `content`.
- Which iteration closes this: Iter 1.

### Drift 2: `expand=note` in task endpoint does not work

- What is documented: The old skill docs say `task_get` returns a `note` field; `expand=note` was tested as an embedded-note path.
- What is observed in runtime: `observed-api-shapes.json` shows `note_field_presence: absent` for both `GET /v2/task/{id}` and `GET /v2/task/{id}?expand=note`.
- Where in code: `cli.py:513-517` defines `task_get` with only `id`; derived note enrichment uses separate `/v2/note` calls at `cli.py:1608`, `cli.py:1661`, and `cli.py:1705`.
- Which iteration closes this: Iter 1.

### Drift 3: Tool count mismatch

- What is documented: `README.md:9` says 56 tools; `SKILL.md:3` and `SKILL.md:106` say 63 tools.
- What is observed in runtime: `tools.json` contains 60 entries; `cli.py:395-1018` contains 63 runtime catalog entries.
- Where in code: `cli.py:984`, `cli.py:993`, and `cli.py:1009` define `task_full`, `project_tasks_full`, and `inbox_list`; `cli.py:1728-1730` registers them in dispatch. These three tools are absent from `tools.json`.
- Which iteration closes this: Iter 4.

### Drift 4: Invalid `--describe` schema types

- What is documented: `decisions.md` chooses JSON Schema draft-07 and JSON Schema type names.
- What is observed in runtime: `--describe` copies catalog type strings such as `int`, `str`, `bool`, and `list` into `inputSchema.properties.*.type`; valid JSON Schema needs `integer`, `string`, `boolean`, and `array`. `object` is already valid where used.
- Where in code: catalog examples include `cli.py:400`, `cli.py:409`, `cli.py:424`, and `cli.py:536`; `--describe` emits `v["type"]` directly at `cli.py:2148`.
- Which iteration closes this: Iter 4.

### Drift 5: Hardcoded `maxCount=1000`

- What is documented: Pagination contract is `offset` + `maxCount`, max 1000, no cursor.
- What is observed in runtime: Several flows fetch one page with `maxCount=1000`, so accounts with more than 1000 matching items can be silently truncated.
- Where in code: `cli.py:1175`, `cli.py:1186`, `cli.py:1630`, `cli.py:1640`, `cli.py:1681`, `cli.py:1686`, and `cli.py:1798`.
- Which iteration closes this: Iter 2.

### Drift 6: Client-side filtering instead of server-side

- What is documented: `task_list` supports `project_id`, mapped to API parameter `projectId`.
- What is observed in runtime: `_project_tasks_full_handler` fetches up to 1000 tasks without `projectId`, then filters by `projectId` in Python.
- Where in code: `cli.py:186` maps `projectId`; `cli.py:507` documents `project_id`; `cli.py:1627-1644` fetches all tasks and filters client-side.
- Which iteration closes this: Iter 2.

### Drift 7: Two project caches

- What is documented: `references/projects.json` is auto-managed by `rebuild_references`; `projects_cache.md` is also an auto-managed project tree.
- What is observed in runtime: `references/projects.json` uses `cache_ttl_days` from `config.json`, default 30 days; `projects_cache.md` uses a separate hardcoded 7-day TTL.
- Where in code: `cli.py:1733-1777` handles `references/projects.json` TTL via `cache_ttl_days`; `cli.py:1784-1785` defines `CACHE_MAX_AGE_DAYS = 7` and `projects_cache.md`.
- Which iteration closes this: Iter 3.

### Drift 8: Cache writes `config.json`

- What is documented: Cache refresh is described as an automatic side effect of tool execution.
- What is observed in runtime: The project-cache refresh rewrites the full `config.json` object, including the token field, to update `cache_updated`. `_check_and_refresh_cache` triggers reference cache rebuilds but does not itself write `config.json`; the write path is the adjacent project-cache refresh path called before it.
- Where in code: `_check_and_refresh_cache` is `cli.py:1733-1777`; `_refresh_project_cache` writes `cfg` to `config.json` at `cli.py:1846-1849`; main auto-refresh calls `_maybe_auto_refresh_cache` then reloads config at `cli.py:2187-2191`, and calls `_check_and_refresh_cache` at `cli.py:2195-2198`.
- Which iteration closes this: Iter 3.
