# Secrets Policy (T0.9)

## 1. Token storage

- Path: `C:\Users\kirill.gorosov\.claude\skills\singularity\config.json`
- Field: `token` (Bearer)
- `.gitignore` confirmation: `config.json` excluded at line 1

## 2. Token retrieval at runtime

- `cli.py:134-139` function `load_config()` is the only entry point.
- After Iteration 6 refactor: only the `config.py` module reads `config.json`.
- Nothing else should read `config.json` directly.

## 3. Snapshot artifact rules

These rules apply to all files in `references/contract/` and `tests/fixtures/`.

- Never write the token value.
- Replace user content (task titles, names, notes) with JSON Schema type placeholders (`string`, `integer`, etc.).
- `observed-api-shapes.json` is the canonical example of correct redaction.
- Any new snapshot fixture must follow the same redact-by-type policy before it is committed or shared.

## 4. Cache layer must NOT write config.json

- Current violation: `_check_and_refresh_cache` (`cli.py:1849`) rewrites `config.json` on every auto-refresh.
- Risk: race condition with concurrent runners (stale in-memory token snapshot overwrites fresh token).
- Tracked for fix in Iteration 3 (T3.9).

## 5. --doctor behaviour without token

- Missing `config.json`: exit code 2, human-readable error with instructions to create the file.
- Empty/invalid token: structured JSON response `{status: fail, checks: [...]}` with exit code 1, no traceback, no `lastcheck` timestamp written.
- `--doctor` must have zero side effects on `config.json` or cache files.

## 6. Token rotation

- User edits `config.json` manually.
- Skill must never attempt to update or refresh the token automatically.
- No refresh tokens stored.

## 7. Logging redaction rule

- Never log the `Authorization` header.
- Never log a full URL containing a token in the query string.
- On errors: log only short error message and HTTP status, not full request/response body.
