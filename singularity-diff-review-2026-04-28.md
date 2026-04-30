# Singularity Diff Review

Date: 2026-04-28

Scope: review by diff and working tree, focusing only on critical and serious issues.

## Findings

### 1. [P1] Partial task-group rebuilds are marked complete and healthy

File: `C:\Users\kirill.gorosov\.claude\skills\singularity\cli.py:1107-1149`

`iterate_pages()` returns `partial=true` on fetch failures, but the task-group rebuild path ignores that signal entirely. `_rebuild_references_handler()` increments `tg_errors_count` only on thrown exceptions, then derives `_meta.complete` solely from `tg_errors_count == 0`.

Reproduction:
- use a mock client where page 2 of `/v2/task-group` fails;
- `_rebuild_references_handler()` returns `status='ok'`;
- `partial=false`;
- `task_groups.json` is written with `_meta.complete=true`.

Impact:
- a truncated project-to-task-group mapping is published as authoritative;
- downstream cache consumers cannot distinguish healthy data from partial data.

### 2. [P1] Incomplete reference caches are still consumed as authoritative data

File: `C:\Users\kirill.gorosov\.claude\skills\singularity\cli.py:862-957`

The rebuild path now writes `_meta.complete=false` for partial `projects.json` and `tags.json`, but the runtime read path ignores that metadata and indexes whatever is present. `_load_indexed_projects()` and `_load_indexed_tags()` build indexes directly from the cache body, and `find_project` / `find_tag` only rebuild on a miss.

Reproduction:
- provide a `tags.json` with `_meta.complete=false` and one tag;
- call `_find_tag_handler(..., exact=True)`;
- it returns `found=true` with no degradation signal.

Impact:
- after a partial rebuild, search tools can keep serving knowingly incomplete data as if it were healthy;
- this defeats the purpose of adding completeness metadata.

### 3. [P1] Generated JSON Schema still lies about array element types

File: `C:\Users\kirill.gorosov\.claude\skills\singularity\scripts\regen_metadata.py:34-52`

The metadata generator hardcodes every array parameter to `items.type = string`, regardless of the actual payload contract. That makes published schemas wrong for `note_create.content` / `note_update.content` (Delta objects) and for numeric arrays like `task.notifies`.

Impact:
- schema-driven hosts can reject valid payloads;
- generated UIs and tool adapters can be wrong;
- the current test suite stays green because it validates only draft-07 shape, not semantic correctness of array item types.

## Notes

- This review intentionally excludes code-style and cosmetic remarks.
- Focus was limited to critical and serious correctness / contract issues.
