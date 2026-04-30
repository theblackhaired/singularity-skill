# Singularity v1.5.0 — Design Review

**Date:** 2026-04-28
**Reviewer:** Codex (cross-review of design proposal by Claude)
**Status:** Design accepted with major revisions; implementation order changed.

## Goals of v1.5.0

1. **One source of truth for projects.** Eliminate `projects_cache.md` (human-curated markdown). `references/projects.json` becomes the only source. No `--pretty` markdown rendering.
2. **Preserve project descriptions.** The markdown file held free-form descriptions per project — needed by AI agents using the skill for context. Must be migrated into JSON.
3. **Major architectural cleanup.** Split `cli.py` (~2200 LOC) into `crud.py`, `derived.py`, `main.py`, extend `cache.py`. Pure refactor under parity-test protection.

## Critical findings from Codex review

### 1. Descriptions live in `project_meta.json`, NOT in markdown
The original assumption — that descriptions are free-form text in `projects_cache.md` — was wrong. The markdown file contains only a tree of titles+ids. Descriptions are already in `references/project_meta.json`. **Migration becomes trivial code-to-code transfer; no markdown parsing or AI extraction needed.**

### 2. Code auto-recreates `projects_cache.md`
Functions `_maybe_auto_refresh_cache` and `_refresh_project_cache` regenerate the markdown on every `--call` if missing. Archiving the file alone is insufficient — these code paths must be removed first, otherwise the file respawns on next invocation.

### 3. Migration trigger "all descriptions null" is broken
Current `references/projects.json` already has `with_description: 4`. The trigger never fires. **Replace with explicit state marker** `_meta.description_migration: {"version": 1, "status": "pending|complete"}`.

### 4. Rebuild overwrites descriptions
Current `_rebuild_references_handler` populates descriptions from `project_meta.json` and overwrites `projects.json`. Without changes, any user edit via `project_describe` will be silently destroyed on next rebuild. **Rebuild must merge by id** — preserve existing descriptions in `projects.json`.

### 5. Multi-machine sync breaks lock files
This skill is synced between machines C: and Z:. Lock files relying on PID/host are unreliable across sync boundaries. **Use compare-and-swap (CAS) via sha256 of `projects.json` instead** for safe concurrent writes.

### 6. Discovery commands must NOT block on migration
If `migration_pending` blocks `--list` and `--describe`, tool hosts cannot even discover what's available. These read-only meta-commands must work regardless of migration state.

## Edge cases identified

### Critical
- Migration trigger condition (described above)
- Rebuild overwriting descriptions (described above)
- Auto-recreation of `projects_cache.md` (described above)

### Important
- `projects_cache.md` archive collision: if `.pre-1.5.0.bak` exists, must use timestamped variant (`projects_cache.md.pre-1.5.0.<timestamp>.<hash>.bak`)
- `--refresh-cache` flag currently means "write `projects_cache.md`" — must be removed
- `project_describe` is a local write but doesn't match `WRITE_TOOLS` suffix rules — must define `LOCAL_WRITE_TOOLS` policy explicitly
- Case-folding/Unicode normalization for IDs and titles (Russian text in current data)
- `cache_ttl_days: null` documented in SKILL.md but `_check_and_refresh_cache` does `age_days >= cache_ttl_days` — would throw `TypeError` on null

### Nice-to-have
- `with_description` counter must update when descriptions change
- `generated_at` semantics — separate API freshness from metadata freshness

## Contract specifications (revised)

### `migration_pending` response shape
```json
{
  "status": "migration_pending",
  "code": "MIGRATION_PENDING",
  "source_file": "projects_cache.md",
  "source_path": "<absolute path>",
  "archive_path": "<absolute path>.pre-1.5.0.bak",
  "projects_total": 56,
  "projects_with_description": 4,
  "projects_without_description": [{"id": "P-...", "title": "..."}],
  "next_action": {
    "tool": "project_describe",
    "batch_arg": {"P-...": "description"}
  }
}
```

### `project_describe` parameters
- `id: string` — single mode
- `text: string` — single mode
- `batch: object<string, string|null>` — bulk mode
- `batch_file: string` — path to JSON file (for very long lists)
- `force: boolean = false` — overwrite existing without warning
- `dry_run: boolean = false` — preview changes without writing
- `base_sha256: string | null` — CAS check

**Semantics:**
- `null` → delete description
- Empty string → reject as `INVALID_DESCRIPTION` (unless `allow_empty=true`)
- Multiple matches by title → require id

### Standardized error codes
`MIGRATION_PENDING`, `PROJECT_NOT_FOUND`, `DESCRIPTION_EXISTS`, `INVALID_DESCRIPTION`, `BATCH_INVALID`, `CAS_CONFLICT`, `CACHE_CORRUPT`, `CACHE_BUSY`, `ARCHIVE_CONFLICT`, `MIGRATION_SOURCE_EMPTY`.

### `PROJECT_NOT_FOUND` shape
```json
{
  "status": "error",
  "code": "PROJECT_NOT_FOUND",
  "invalid_ids": ["P-bad"],
  "available_projects": [{"id": "P-...", "title": "..."}],
  "available_count": 56
}
```

### SKILL.md migration handling instruction
> If a command returns `MIGRATION_PENDING`, read `source_path`, prepare a JSON object keyed by project ID, call `project_describe` once with batch, then rerun the original command. Do not edit `projects_cache.md`; it is archived by the tool after a successful migration.

## Architectural risks

- **Multi-machine concurrency:** lock files unreliable across C:/Z: sync. Rely on CAS + idempotent migration markers.
- **TTL background refresh** is impossible in short-lived CLI without daemon. Drop background refresh; refresh synchronously when needed.
- **Refactor + migration in one pass** hides regressions. Behavior changes first in monolith, module split second.
- **Version drift:** `cli.py` says 1.4.2, `SKILL.md` says 1.4.0. v1.5.0 must establish single authoritative version source.
- **Cache check failures** are currently swallowed by `--call`. Dispatcher must propagate `CACHE_CORRUPT` deterministically.

## Recommended implementation order

### Stage 1 — Behavior in monolith (no module split yet)

1. **Freeze parity:** record `--list`, `--describe`, `--doctor`, `--verify-cache`, `--verify-metadata` snapshots; confirm 92 tests pass.
2. **Remove markdown cache runtime paths:** delete `_maybe_auto_refresh_cache`, `_refresh_project_cache`, `CACHE_FILE`, `CACHE_MAX_AGE_DAYS`, `--refresh-cache`. Update SKILL.md to remove all references to reading `projects_cache.md`.
3. **Description-preserving rebuild:** rewrite `_rebuild_references_handler` to load existing `projects.json`, carry `description` forward by id, only fall back to `project_meta.json` on first import. Stop using `project_meta.json` as authoritative source.
4. **Add `project_describe`** to `TOOL_CATALOG`, `TOOL_DISPATCH`, with CAS via `base_sha256`, batch validation, `force`, `dry_run`, structured errors.
5. **Add `_meta.description_migration`** state machine. Idempotent pending/complete handling.
6. **Idempotent archiving:** timestamped backup name if `.pre-1.5.0.bak` already exists.
7. **Update artifacts:** `tools.json`, `SKILL.md`, `--describe` snapshots, version → 1.5.0 from single authoritative location.
8. **Tests:** 12+ new tests covering all error codes and edge cases.

### Stage 2 — Module split (only after Stage 1 ships and is stable)

1. `crud.py` first
2. `derived.py` second
3. Extended `cache.py` third
4. `main.py` last
5. Run parity tests after each extraction; do not batch.

## Required test cases

1. `projects_cache.md` exists, `projects.json` has descriptions: migration state detected via `_meta.description_migration`, not "all null" check.
2. `project_describe` updates description, `rebuild_references` preserves it.
3. `with_description` counter updates correctly after batch.
4. Process crashes between JSON write and md archive: rerun completes archive, no duplicate descriptions.
5. `.pre-1.5.0.bak` already exists: timestamped backup path used.
6. `--list` and `--describe project_describe` return data while migration is pending (not blocked).
7. `project_describe` with invalid id returns `PROJECT_NOT_FOUND` JSON on stdout (not only stderr).
8. Malformed JSON batch returns `BATCH_INVALID`, leaves `projects.json` byte-identical.
9. CAS conflict: file changed between read and replace; returns `CAS_CONFLICT`, preserves both states.
10. `read_only=true` behavior for `project_describe` matches explicit `LOCAL_WRITE_TOOLS` policy.
11. `cache_ttl_days: null` does not throw `TypeError`; follows documented behavior.
12. Stale cross-machine lock does not block reads; only blocks rebuild/migration writes via `CACHE_BUSY`.

## Rejected design proposals

- **"JSON only" while keeping `--refresh-cache`** — contradictory; flag must go.
- **"All descriptions null" as migration detector** — current data already disproves this.
- **Writing descriptions only to `projects.json`** — without rebuild merge logic, descriptions are silently destroyed.
- **Blocking every command on migration pending** — discovery commands must remain accessible.
- **Sync correctness based on lock file alone** — unreliable across C:/Z: sync. Use CAS.
- **Combined refactor + migration in unverified commit** — too many public surfaces tied together; split work.
- **Prompt-enforced cache integrity** — keep deterministic Python checks, never delegate to AI.

## Status

- ✅ Design accepted with all critical revisions incorporated
- ➡️ Stage 1 implementation starting (behavior in monolith)
- ⏸ Stage 2 (module split) deferred until Stage 1 stable

## References

- Original review by Codex: agent run on 2026-04-28
- Predecessor: `singularity-diff-review-2026-04-28.md` (closed P1 bugs, version 1.4.2)
- Prior spec: `singularity-skill-implementation-spec-2026-04-26.md`
