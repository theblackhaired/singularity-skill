"""CLI contract tests for read-only metadata and config safety."""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "cli.py"
TOOLS = ROOT / "tools.json"


def _run(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
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


class TestCliParity(unittest.TestCase):
    def test_list_matches_tools_json(self):
        actual = sorted(json.loads(_run("--list")), key=lambda tool: tool["name"])
        external = json.loads(TOOLS.read_text(encoding="utf-8"))
        expected = sorted([
            {"name": tool["name"], "description": tool["description"]}
            for tool in external
        ], key=lambda tool: tool["name"])
        self.assertEqual(actual, expected)

    def test_doctor_does_not_modify_config(self):
        cfg = ROOT / "config.json"
        if not cfg.exists():
            self.skipTest("config.json missing")
        before = hashlib.md5(cfg.read_bytes()).hexdigest()
        subprocess.run(
            [sys.executable, str(CLI), "--doctor"],
            cwd=ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
        after = hashlib.md5(cfg.read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
