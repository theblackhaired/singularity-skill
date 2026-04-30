# Singularity App Skill

## What's New

**Jedi Techniques (Dorofeev)** — optional productivity skill with 8 modes based on Maxim Dorofeev's "Jedi Techniques" book. Brain dump, task reviews, decomposition, focus mode, incubator, context agendas, trigger lists, daily checklists. Activates only on request via natural language triggers. See [`singularity-jedi.md`](singularity-jedi.md).

Script-based CLI skill for [Singularity App](https://singularity-app.com) task management API.

64 tools covering 11 resources: projects, tasks, task groups, notes, kanban boards, habits, habit progress, checklists, tags, time tracking. Includes derived batch tools (`task_full`, `project_tasks_full`, `inbox_list`) and cache helpers (`rebuild_references`, `project_describe`, `find_project`, `find_tag`, `generate_meta_template`).

## Quick start

1. Create `config.json`:
```json
{
  "base_url": "https://api.singularity-app.com",
  "token": "YOUR_API_TOKEN",
  "read_only": false
}
```

2. Run:
```bash
python cli.py --list
python cli.py --describe task_list
python cli.py --call '{"tool": "project_list", "arguments": {"max_count": 10}}'

# Self-checks (read-only, no side effects):
python cli.py --doctor              # full sanity check
python cli.py --verify-cache        # cache integrity (schema_version, complete=True)
python cli.py --verify-metadata     # tools.json sync with runtime catalog
```

## Requirements

- Python 3.10+ (uses PEP 604 union syntax)
- No external runtime dependencies (pure stdlib). Test deps in `requirements-dev.txt`: `jsonschema`.

## Documentation

Full tool reference, usage examples, and data format notes: [SKILL.md](SKILL.md)

## API reference

[Singularity REST API v2](https://api.singularity-app.com/v2/api-json)
