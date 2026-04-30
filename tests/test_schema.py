"""T4.8 — Schema validation tests.

For every tool in TOOL_CATALOG, the `--describe` output's `inputSchema` must
validate against JSON Schema draft-07 meta-schema (see decisions.md §JSON Schema).

Also enforces tools.json/runtime sync invariant (T4.7 surface).

Run:
    python -m unittest tests.test_schema -v
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cli import TOOL_CATALOG  # noqa: E402

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


VALID_JSON_SCHEMA_TYPES = {"integer", "string", "number", "boolean", "array", "object", "null"}


def _describe(tool_name: str) -> dict:
    """Run cli.py --describe <tool> and parse result."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "cli.py"), "--describe", tool_name],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"cli.py --describe {tool_name} exited {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )
    return json.loads(result.stdout)


def _tools_json_schema(tool_name: str) -> dict:
    """Load one generated tools.json schema by tool name."""
    with open(ROOT / "tools.json", encoding="utf-8") as f:
        tools = json.load(f)
    for tool in tools:
        if tool.get("name") == tool_name:
            return tool
    raise AssertionError(f"tools.json missing tool: {tool_name}")


class TestDescribeSchema(unittest.TestCase):
    """T4.3 invariant: every --describe output is valid JSON Schema draft-07."""

    @classmethod
    def setUpClass(cls):
        cls.tool_names = list(TOOL_CATALOG.keys())
        cls.assertEqual_count = 64
        if len(cls.tool_names) != cls.assertEqual_count:
            print(f"WARN: expected {cls.assertEqual_count} tools, "
                  f"got {len(cls.tool_names)}",
                  file=sys.stderr)

    def test_catalog_has_64_tools(self):
        """Runtime catalog has expected 64 tools."""
        self.assertEqual(len(self.tool_names), 64)

    def test_all_describe_outputs_have_valid_top_level(self):
        """Every --describe response has name/description/inputSchema."""
        for name in self.tool_names:
            with self.subTest(tool=name):
                schema = _describe(name)
                self.assertIn("name", schema)
                self.assertIn("description", schema)
                self.assertIn("inputSchema", schema)
                self.assertEqual(schema["name"], name)
                self.assertEqual(schema["inputSchema"]["type"], "object")

    def test_all_property_types_are_valid_json_schema(self):
        """No property uses Python type names (int/str/list/object/...).

        Closes Drift 4 (known-drifts.md). Iteration 4 / T4.3.
        """
        for name in self.tool_names:
            with self.subTest(tool=name):
                schema = _describe(name)
                props = schema["inputSchema"].get("properties", {})
                for k, p in props.items():
                    t = p.get("type")
                    self.assertIn(
                        t, VALID_JSON_SCHEMA_TYPES,
                        f"{name}.{k} has invalid JSON Schema type: {t!r}"
                    )

    def test_arrays_have_items(self):
        """Every property with type=array has `items` (draft-07 requirement)."""
        for name in self.tool_names:
            with self.subTest(tool=name):
                schema = _describe(name)
                props = schema["inputSchema"].get("properties", {})
                for k, p in props.items():
                    if p.get("type") == "array":
                        self.assertIn(
                            "items", p,
                            f"{name}.{k}: array type without `items`"
                        )

    def test_objects_have_properties(self):
        """Every property with type=object has `properties` (defensive)."""
        for name in self.tool_names:
            with self.subTest(tool=name):
                schema = _describe(name)
                props = schema["inputSchema"].get("properties", {})
                for k, p in props.items():
                    if p.get("type") == "object":
                        self.assertIn(
                            "properties", p,
                            f"{name}.{k}: object type without `properties`"
                        )

    @unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema lib not installed")
    def test_meta_schema_validation(self):
        """jsonschema.Draft7Validator.check_schema passes for every tool."""
        for name in self.tool_names:
            with self.subTest(tool=name):
                schema = _describe(name)
                try:
                    jsonschema.Draft7Validator.check_schema(
                        schema["inputSchema"]
                    )
                except jsonschema.SchemaError as exc:
                    self.fail(f"{name}: invalid draft-07 schema: {exc}")


class TestToolsJsonSync(unittest.TestCase):
    """T4.7 invariant: tools.json must match runtime catalog."""

    def test_tools_json_in_sync(self):
        """scripts/regen_metadata.py --check exits 0 (no drift)."""
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "regen_metadata.py"),
             "--check"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            f"tools.json drift detected:\n{result.stdout}\n{result.stderr}"
        )

    def test_tools_json_count(self):
        """tools.json has exactly len(TOOL_CATALOG) entries."""
        with open(ROOT / "tools.json", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), len(TOOL_CATALOG))

    def test_tools_json_includes_derived(self):
        """task_full, project_tasks_full, inbox_list present in tools.json."""
        with open(ROOT / "tools.json", encoding="utf-8") as f:
            data = json.load(f)
        names = {t["name"] for t in data}
        for derived in ("task_full", "project_tasks_full", "inbox_list"):
            self.assertIn(derived, names,
                f"tools.json missing derived tool: {derived}")


class TestArrayItemSchemas(unittest.TestCase):
    """Array item schemas must match the actual API payload contract."""

    def _assert_property_items(
        self,
        source: str,
        tool_name: str,
        property_name: str,
        expected_items: dict,
    ) -> None:
        if source == "describe":
            schema = _describe(tool_name)
        elif source == "tools.json":
            schema = _tools_json_schema(tool_name)
        else:
            raise AssertionError(f"unknown source: {source}")

        prop = schema["inputSchema"]["properties"][property_name]
        self.assertEqual(prop.get("type"), "array")
        self.assertEqual(
            prop.get("items"),
            expected_items,
            f"{source} {tool_name}.{property_name} has wrong items schema",
        )

    def test_note_content_arrays_are_object_items(self):
        """Delta arrays contain op objects, not strings."""
        for source in ("describe", "tools.json"):
            with self.subTest(source=source, tool="note_create"):
                self._assert_property_items(
                    source, "note_create", "content", {"type": "object"}
                )
            with self.subTest(source=source, tool="note_update"):
                self._assert_property_items(
                    source, "note_update", "content", {"type": "object"}
                )

    def test_task_notifies_arrays_are_integer_items(self):
        """Notification offsets are integer minute values."""
        for source in ("describe", "tools.json"):
            with self.subTest(source=source, tool="task_create"):
                self._assert_property_items(
                    source, "task_create", "notifies", {"type": "integer"}
                )
            with self.subTest(source=source, tool="task_update"):
                self._assert_property_items(
                    source, "task_update", "notifies", {"type": "integer"}
                )

    def test_confirmed_string_array_stays_string_items(self):
        """Tag IDs are still represented as string arrays."""
        for source in ("describe", "tools.json"):
            with self.subTest(source=source):
                self._assert_property_items(
                    source, "project_create", "tags", {"type": "string"}
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
