"""CLI parity tests — byte-identical comparison of read-only invocations.

T0.12 — Iteration 0 baseline.

These tests are the safety net for Iteration 6 (modular refactor). Any
change to read-only command output that is intentional MUST regenerate
the snapshot in the same commit, with rationale in the message.

Run: python -m unittest tests.test_cli_parity -v
"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "tests" / "snapshots" / "cli"
CLI = ROOT / "cli.py"


def _run(*args: str) -> str:
    """Run cli.py with args, return stdout text. Always uses same Python."""
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"cli.py {' '.join(args)} exited {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )
    return result.stdout


def _read_snapshot(name: str) -> str:
    return (SNAPSHOTS / name).read_text(encoding="utf-8")


class TestCliParity(unittest.TestCase):
    """Read-only CLI invocations must produce byte-identical output to baseline.

    This guards against silent drift during refactoring. Failures here mean:
      (a) intentional change → regenerate snapshot in same commit, OR
      (b) regression → fix the code, do not touch the snapshot.
    """

    def test_list_baseline(self):
        """`python cli.py --list` matches snapshot."""
        actual = _run("--list")
        expected = _read_snapshot("list.txt")
        self.assertEqual(actual, expected,
            "drift in --list output; regen with: "
            "python cli.py --list > tests/snapshots/cli/list.txt")

    def test_describe_project_list_baseline(self):
        """`python cli.py --describe project_list` matches snapshot."""
        actual = _run("--describe", "project_list")
        expected = _read_snapshot("describe_project_list.txt")
        self.assertEqual(actual, expected,
            "drift in --describe project_list output; regen with: "
            "python cli.py --describe project_list "
            "> tests/snapshots/cli/describe_project_list.txt")

    def test_list_contains_64_tools(self):
        """Smoke check: --list returns 64 tools."""
        import json
        out = _run("--list")
        tools = json.loads(out)
        self.assertEqual(len(tools), 64,
            f"expected 64 tools, got {len(tools)}")

    def test_doctor_no_side_effects_on_config(self):
        """T0.13 invariant: --doctor must not modify config.json."""
        import hashlib
        cfg = ROOT / "config.json"
        if not cfg.exists():
            self.skipTest("config.json missing — skip live doctor check")
        before = hashlib.md5(cfg.read_bytes()).hexdigest()
        # --doctor may exit 1 if API unreachable; we don't care, only no-write
        subprocess.run(
            [sys.executable, str(CLI), "--doctor"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=30,
            check=False,
        )
        after = hashlib.md5(cfg.read_bytes()).hexdigest()
        self.assertEqual(before, after,
            "--doctor MUST NOT modify config.json")


if __name__ == "__main__":
    unittest.main(verbosity=2)
