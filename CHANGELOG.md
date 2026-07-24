# Changelog

## 1.5.5 — 2026-07-24

- Removed obsolete implementation plans, review reports, stale contract notes,
  and pre-1.5.0 CLI snapshots from the installable skill.
- Made `tools.json` the single committed metadata contract and replaced
  duplicate snapshots with direct runtime-to-contract tests.
- Condensed `SKILL.md`, the README, test guidance, and retained contract notes
  around the current 65-tool implementation.
- Removed broken references and internal iteration labels from maintained
  documentation and source comments.

## 1.5.4 — 2026-07-24

- `find_project` validates the local project cache against the live server
  before every lookup, including cache hits.
- Incremental deltas preserve local descriptions and reflect renamed, moved,
  newly created, and removed projects.
- Cache synchronization uses server watermarks with overlap, follows
  pagination totals, and fails closed when validation cannot complete.
- Cross-process locking protects project-cache read/modify/write operations.
- Full reference rebuilds pace per-project task-group requests to avoid burst
  rate limits.

## 1.5.3 — 2026-07-24

- Added `task_move`, which resolves and validates the target `Q-*` section
  before moving a task between projects.
- Refuses ambiguous, missing, foreign, removed, or partially fetched sections.
- Verifies the resulting `projectId` and `group` after the move.
- Read-only mode blocks `task_move`.

## 1.5.2 — 2026-07-21

- Added explicit `task_update.group` support for project sections.
- Blocked project changes without the target project's section.
- Clarified that `task_update.parent` accepts a parent task (`T-*`), not a
  project section (`Q-*`).

## 1.5.1 — 2026-05-22

- Fixed note resolution for `task_full`, `project_tasks_full`, and
  `inbox_list`.
- Notes now use deterministic single-resource lookup and validate
  `containerId`, avoiding arbitrary results from an unreliable list filter.
- A missing note and a shape mismatch are reported explicitly.

## 1.5.0 — 2026-04-28

- Replaced markdown project caches with `references/projects.json`.
- Added `project_describe` with batch mode, dry-run, compare-and-swap checks,
  atomic validation, and structured errors.
- Added description migration state and idempotent archival of the legacy
  markdown cache.
- Split CRUD, derived operations, cache behavior, client behavior, errors,
  configuration, and resource definitions into focused modules.
- Added generated `tools.json`, JSON Schema validation, metadata drift checks,
  cache verification, API smoke checks, pagination, atomic cache writes, and
  token redaction.
