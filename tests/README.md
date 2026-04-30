# Singularity skill вЂ” Test Suite

Quick verification before merge / after edits.

## Run all tests

```bash
cd C:\Users\kirill.gorosov\.claude\skills\singularity
python -m unittest discover tests -v
# Expected: 82 tests, all OK
```

Actual count source: 82 lines matching `^\s*def test_` across `tests/test_*.py`.

## Run-time self-checks (no install needed)

```bash
python cli.py --doctor             # 8 read-only sanity checks
python cli.py --verify-cache       # references/*.json schema_version + complete=True
python cli.py --verify-metadata    # tools.json sync with runtime catalog
python cli.py --verify-api         # 6 canonical endpoints reachable + shapes match
```

## Per-iteration verification

(For reviewer to reproduce each iteration's claims independently.)

### Iteration 0 вЂ” Baseline
```bash
python cli.py --doctor
python -m unittest tests.test_cli_parity -v
```
- Claim: 8 doctor checks pass, CLI snapshot byte-identical.

### Iteration 1 вЂ” Note correctness
```bash
python -m unittest tests.test_note_resolver -v
```
- Claim: note_resolver expands note IDs correctly, handles missing gracefully.
- Closes: Drift 1 (notes), Drift 2 (expand).

### Iteration 2 вЂ” Pagination
```bash
python -m unittest tests.test_pagination -v
```
- Claim: iterate_pages handles maxCount cap and filter propagation.
- Closes: Drift 5 (maxCount), Drift 6 (filter).

### Iteration 3 вЂ” Cache safety
```bash
python -m unittest tests.test_cache tests.test_config_safety -v
```
- Claim: cache.py atomic writes, no partial state on crash, config.json is not rewritten by cache refresh.
- Closes: Drift 8 (config write hazard).

### Iteration 4 вЂ” Schema output
```bash
python cli.py task_list --describe
python -m unittest tests.test_schema -v
```
- Claim: --describe output is valid JSON Schema draft-07 for all tools.
- Closes: Drift 3 (counts), Drift 4 (schema).

### Iteration 5 вЂ” Parity & contract tests
```bash
python -m unittest tests.test_cli_parity tests.test_contract_client tests.test_contract_derived tests.test_describe_snapshots -v
```
- Claim: CLI snapshots match; client and derived contract assertions pass; describe_all.json covers all 64 runtime tools.
- Delivers: refactor safety net.

### Iteration 6 вЂ” Module split
```bash
python -m unittest discover tests -v
```
- Claim: all tests are the required guard for the monolith -> modules refactor.
- Current status: CHANGELOG marks Iteration 6 modular refactor as deferred; `resources.py` and `doctor.py` are not part of the current test inventory.

### Iteration 7 вЂ” API hardening
```bash
python cli.py --verify-api
python -m unittest discover tests -v
```
- Claim: 6 canonical endpoints reachable, shapes validated by the live smoke command.
- Delivers: known-limitations documented and API hardening partially landed.

### Iteration 8 вЂ” Residual cleanup
```bash
python -m unittest discover tests -v
```
- Claim: all 82 tests pass after review fixes.
- Current status: backlog cleanup partially landed per CHANGELOG.

## Test files inventory

| File | Iter | Purpose |
|---|---:|---|
| `tests/test_cache.py` | 3 | Atomic writes, cache metadata, migration, timestamp parsing |
| `tests/test_cli_parity.py` | 0/5 | Read-only CLI snapshot parity and doctor side-effect guard |
| `tests/test_config_safety.py` | 3 | Cache refresh must not rewrite config.json |
| `tests/test_contract_client.py` | 5/7 | HTTP client CRUD, retries, redaction, URL safety |
| `tests/test_contract_derived.py` | 5/7 | Derived tool status, degraded, partial, filter contracts |
| `tests/test_describe_snapshots.py` | 5 | `describe_all.json` snapshot matches all runtime tools |
| `tests/test_note_resolver.py` | 1 | Note resolver success, degraded, URL, capability paths |
| `tests/test_pagination.py` | 2 | Pagination, truncation, wrapper detection, throttling |
| `tests/test_schema.py` | 4 | JSON Schema draft-07 and tools.json metadata sync |

## Test method counts

| File | Test methods |
|---|---:|
| `tests/test_cache.py` | 22 |
| `tests/test_cli_parity.py` | 4 |
| `tests/test_config_safety.py` | 4 |
| `tests/test_contract_client.py` | 9 |
| `tests/test_contract_derived.py` | 5 |
| `tests/test_describe_snapshots.py` | 2 |
| `tests/test_note_resolver.py` | 12 |
| `tests/test_pagination.py` | 15 |
| `tests/test_schema.py` | 9 |
| **Total** | **82** |

## Snapshots

`tests/snapshots/cli/` вЂ” byte-identical CLI output baselines.
- `list.txt`, `describe_project_list.txt` вЂ” read-only invocations
- `describe_all.json` вЂ” all 64 tools' --describe schemas

Regen via `python scripts/gen_describe_snapshots.py` (intentional drift only вЂ” explain in commit).

## Mocked vs live

- **Unit/contract tests** вЂ” pure mocked, no network.
- **Live smoke** вЂ” only `--verify-api` and `--doctor` make HTTP calls.
- **No write tests by default.** Set `SINGULARITY_TEST_ACCOUNT=1` to enable opt-in.

## What each iteration delivered

(Cross-reference singularity-skill-implementation-spec-2026-04-26.md and CHANGELOG.md.)

| Iter | Delivered | Closed drift / risk |
|---|---|---|
| 0 | baseline + decisions + --doctor + CLI parity skeleton | вЂ” |
| 1 | note_resolver per Decision A | Drift 1 (notes), Drift 2 (expand) |
| 2 | pagination.py + iterate_pages | Drift 5 (maxCount), Drift 6 (filter) |
| 3 | cache.py atomic + T3.9 config safety | Drift 8 (config write hazard) |
| 4 | --describe -> JSON Schema draft-07 + tools.json sync | Drift 3 (counts), Drift 4 (schema) |
| 5 | parity snapshots + client/derived contract tests + describe_all coverage | refactor safety net |
| 6 | deferred modular refactor; tests are ready as guard | monolith -> modules risk |
| 7 | --verify-api + Known limitations, partial hardening | live API hardening |
| 8 | partial small fixes from review | residual cleanup |
