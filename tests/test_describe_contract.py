"""Keep ``--describe`` aligned with the committed external tool contract."""

from copy import deepcopy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cli import TOOL_CATALOG  # noqa: E402

TOOLS_PATH = ROOT / "tools.json"


class TestDescribeContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tools = json.loads(TOOLS_PATH.read_text(encoding="utf-8"))
        cls.expected = {tool["name"]: tool for tool in tools}

    def test_tools_json_has_all_runtime_tools(self):
        runtime = set(TOOL_CATALOG)
        external = set(self.expected)
        self.assertEqual(
            runtime,
            external,
            f"runtime - tools.json = {runtime - external}\n"
            f"tools.json - runtime = {external - runtime}",
        )

    def test_each_describe_matches_tools_json(self):
        for name in sorted(TOOL_CATALOG):
            with self.subTest(tool=name):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "cli.py"), "--describe", name],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=15,
                )
                actual = json.loads(result.stdout)
                expected = deepcopy(self.expected[name])
                expected["inputSchema"] = {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    **expected["inputSchema"],
                }
                self.assertEqual(
                    actual,
                    expected,
                    f"DRIFT in {name}; run `python scripts/regen_metadata.py`",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
