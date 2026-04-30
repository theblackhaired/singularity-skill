"""T5.2 — Byte-identical snapshot tests for --describe across all runtime tools.

If a test fails: that is INTENTIONAL drift — regen via:
    python scripts/gen_describe_snapshots.py
and explain in commit message.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cli import TOOL_CATALOG  # noqa: E402

SNAPSHOT_PATH = ROOT / 'tests' / 'snapshots' / 'cli' / 'describe_all.json'


class TestDescribeSnapshots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SNAPSHOT_PATH.exists():
            raise FileNotFoundError(
                f'Snapshot missing: {SNAPSHOT_PATH}. '
                f'Run: python scripts/gen_describe_snapshots.py'
            )
        cls.expected = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))

    def test_snapshot_has_all_runtime_tools(self):
        """Snapshot must cover every tool in TOOL_CATALOG."""
        runtime = set(TOOL_CATALOG.keys())
        snapshot = set(self.expected.keys())
        self.assertEqual(runtime, snapshot,
            f'runtime - snapshot = {runtime - snapshot}\n'
            f'snapshot - runtime = {snapshot - runtime}')

    def test_each_describe_matches_snapshot(self):
        """For every tool: cli.py --describe <name> matches snapshot exactly."""
        for name in sorted(TOOL_CATALOG.keys()):
            with self.subTest(tool=name):
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'cli.py'), '--describe', name],
                    capture_output=True, text=True, check=True, timeout=15,
                )
                actual = json.loads(result.stdout)
                self.assertEqual(actual, self.expected[name],
                    f'DRIFT in {name} schema. Regen via '
                    f'`python scripts/gen_describe_snapshots.py`')


if __name__ == '__main__':
    unittest.main(verbosity=2)
