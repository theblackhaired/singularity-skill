# Singularity App Skill

Python stdlib client for the Singularity App REST API v2. It supports projects,
tasks, sections, notes, tags, habits, kanban, checklists, and time tracking.

## Setup

Create an ignored `config.json`:

```json
{
  "base_url": "https://api.singularity-app.com",
  "token": "YOUR_API_TOKEN",
  "read_only": false,
  "cache_ttl_days": 30
}
```

Use `"read_only": true` to block every write tool before network access.

## Commands

```powershell
python cli.py --list
python cli.py --describe task_list
python cli.py --call '{"tool":"project_list","arguments":{"max_count":10}}'

python cli.py --doctor
python cli.py --verify-api
python cli.py --verify-cache
python cli.py --verify-metadata
```

Use `find_project` for authoritative project lookup. It validates the local
project cache against the server before returning a result. Use `task_move` for
cross-project moves so `projectId` and the target section (`group`, ID `Q-*`)
are changed and verified together.

The committed [tools.json](tools.json) is generated from the runtime catalog:

```powershell
python scripts/regen_metadata.py
python scripts/regen_metadata.py --check
```

See [SKILL.md](SKILL.md) for operating rules and the official
[REST API v2 schema](https://api.singularity-app.com/v2/api-json) for the
upstream contract.

## Development

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Python 3.10+ is required. Runtime code has no third-party dependencies.
