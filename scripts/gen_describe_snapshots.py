#!/usr/bin/env python3
"""T5.1 — Generate consolidated describe-all snapshot.

Runs `python cli.py --describe <tool>` for every tool in TOOL_CATALOG,
collects results into single JSON file. Test compares against this baseline.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cli import TOOL_CATALOG  # noqa: E402


def main():
    snapshots = {}
    for name in sorted(TOOL_CATALOG.keys()):
        result = subprocess.run(
            [sys.executable, str(ROOT / 'cli.py'), '--describe', name],
            capture_output=True, text=True, check=True, timeout=15,
        )
        snapshots[name] = json.loads(result.stdout)

    out_path = ROOT / 'tests' / 'snapshots' / 'cli' / 'describe_all.json'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(snapshots, indent=2, ensure_ascii=False, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    print(f'Wrote {len(snapshots)} schemas to {out_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
