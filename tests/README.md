# Tests

Run the complete suite:

```powershell
python -m pytest -q
```

Useful focused checks:

```powershell
python -m pytest -q tests/test_cache_lifecycle.py
python -m pytest -q tests/test_task_project_group.py
python -m pytest -q tests/test_schema.py tests/test_describe_contract.py
python scripts/regen_metadata.py --check
```

The suite uses local HTTP fixtures and mock clients. Live read-only checks are
separate:

```powershell
python cli.py --doctor
python cli.py --verify-api
python cli.py --verify-cache
```

`tools.json` is the committed external metadata contract. Tests compare
`--list`, every `--describe` response, and the runtime catalog against it;
separate snapshot files are intentionally unnecessary.

Never commit `config.json`, live tokens, task titles, note contents, or other
user data in fixtures.
