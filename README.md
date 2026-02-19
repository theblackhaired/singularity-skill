# Singularity App Skill

Script-based CLI skill for [Singularity App](https://singularity-app.com) task management API.

56 tools covering 11 resources: projects, tasks, task groups, notes, kanban boards, habits, habit progress, checklists, tags, time tracking.

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
```

## Requirements

- Python 3.8+
- No external dependencies (pure stdlib)

## Documentation

Full tool reference, usage examples, and data format notes: [SKILL.md](SKILL.md)

## API reference

[Singularity REST API v2](https://api.singularity-app.com/v2/api-json)
