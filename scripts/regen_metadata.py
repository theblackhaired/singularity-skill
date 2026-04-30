#!/usr/bin/env python3
"""T4.4 -- Regenerate tools.json + docs from cli.py TOOL_CATALOG.

Usage:
  python scripts/regen_metadata.py            # write
  python scripts/regen_metadata.py --check    # validate, exit 1 on drift
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cli import SKILL_VERSION, TOOL_CATALOG          # noqa: E402
from cache import atomic_write_json, atomic_write_text   # noqa: E402


TYPE_MAP = {
    "int": "integer",
    "str": "string",
    "float": "number",
    "bool": "boolean",
    "list": "array",
    "object": "object",
    "integer": "integer",
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
}

TOOLS_PATH = ROOT / "tools.json"
SKILL_PATH = ROOT / "SKILL.md"
README_PATH = ROOT / "README.md"
CATEGORY_PREFIXES = ("task", "project", "tag", "habit", "kanban", "note", "time")
CATEGORIES = (*CATEGORY_PREFIXES, "derived")


def _schema_for_type(type_name: object) -> dict:
    """Return a JSON Schema fragment for the catalog type name."""
    mapped = TYPE_MAP.get(str(type_name or "string"), "string")
    schema = {"type": mapped}
    if mapped == "array":
        schema["items"] = {"type": "string"}
    elif mapped == "object":
        schema["properties"] = {}
    return schema


def _build_param_schema(param_meta: object) -> dict:
    if not isinstance(param_meta, dict):
        param_meta = {}

    schema = _schema_for_type(param_meta.get("type"))
    if schema.get("type") == "array":
        items = param_meta.get("items")
        if isinstance(items, dict):
            schema["items"] = items
    if schema.get("type") == "object" and "additionalProperties" in param_meta:
        schema["additionalProperties"] = param_meta["additionalProperties"]
    schema["description"] = str(
        param_meta.get("description", param_meta.get("desc", ""))
    )
    if param_meta.get("default") is not None:
        schema["default"] = param_meta["default"]
    return schema


def build_tools() -> list:
    tools = []
    for name in sorted(TOOL_CATALOG):
        meta = TOOL_CATALOG.get(name)
        if not isinstance(meta, dict):
            meta = {}
        params = meta.get("params")
        if not isinstance(params, dict):
            params = {}

        properties = {}
        required = []
        for param_name, param_meta in params.items():
            properties[param_name] = _build_param_schema(param_meta)
            if isinstance(param_meta, dict) and param_meta.get("required") is True:
                required.append(param_name)

        tools.append({
            "name": name,
            "description": str(meta.get("description", meta.get("desc", ""))),
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        })
    return tools


def _replace_between_markers(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    *,
    block: bool = True,
) -> str | None:
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start == -1 or end == -1 or end < start:
        return None

    before = text[:start + len(start_marker)]
    after = text[end:]
    if block:
        return f"{before}\n{replacement}\n{after}"
    return f"{before}{replacement}{after}"


def _replace_all_between_markers(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    *,
    block: bool = True,
) -> str:
    cursor = 0
    chunks = []
    replaced = False

    while True:
        start = text.find(start_marker, cursor)
        if start == -1:
            chunks.append(text[cursor:])
            break

        end = text.find(end_marker, start + len(start_marker))
        if end == -1:
            chunks.append(text[cursor:])
            break

        chunks.append(text[cursor:start + len(start_marker)])
        if block:
            chunks.append(f"\n{replacement}\n")
        else:
            chunks.append(replacement)
        cursor = end
        replaced = True

    return "".join(chunks) if replaced else text


def _extract_between_marker_pairs(
    text: str,
    start_marker: str,
    end_marker: str,
) -> list[str]:
    cursor = 0
    values = []

    while True:
        start = text.find(start_marker, cursor)
        if start == -1:
            break

        value_start = start + len(start_marker)
        end = text.find(end_marker, value_start)
        if end == -1:
            break

        values.append(text[value_start:end].strip())
        cursor = end + len(end_marker)

    return values


def _tool_description(name: str) -> str:
    meta = TOOL_CATALOG.get(name)
    if not isinstance(meta, dict):
        meta = {}
    return str(meta.get("description", meta.get("desc", ""))).strip()


def _category_for_tool_name(name: str) -> str:
    for prefix in CATEGORY_PREFIXES:
        if name.startswith(f"{prefix}_"):
            return prefix
    return "derived"


def _category_tools(category: str) -> list[str]:
    return [
        name
        for name in sorted(TOOL_CATALOG)
        if _category_for_tool_name(name) == category
    ]


def _category_tools_list(category: str) -> str:
    names = _category_tools(category)
    if not names:
        return "_No tools in this category._"
    return "\n".join(f"- `{name}` — {_tool_description(name)}" for name in names)


def _regen_skill_md_text(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0] == "---":
        for idx in range(1, min(len(lines), 20)):
            if lines[idx].startswith("version:"):
                lines[idx] = f"version: {SKILL_VERSION}"
                text = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
                break
            if lines[idx] == "---":
                break

    updated = _replace_all_between_markers(
        text,
        "<!-- TOOLS_COUNT_BEGIN -->",
        "<!-- TOOLS_COUNT_END -->",
        str(len(TOOL_CATALOG)),
        block=False,
    )

    for category in CATEGORIES:
        count_start = f"<!-- CATEGORY_TOOLS_COUNT_BEGIN:{category} -->"
        count_end = f"<!-- CATEGORY_TOOLS_COUNT_END:{category} -->"
        updated = _replace_all_between_markers(
            updated,
            count_start,
            count_end,
            str(len(_category_tools(category))),
            block=False,
        )

        list_start = f"<!-- CATEGORY_TOOLS_LIST_START:{category} -->"
        list_end = f"<!-- CATEGORY_TOOLS_LIST_END:{category} -->"
        updated = _replace_all_between_markers(
            updated,
            list_start,
            list_end,
            _category_tools_list(category),
        )

    return updated


def regen_skill_md_placeholders() -> None:
    if not SKILL_PATH.exists():
        return

    skill_text = SKILL_PATH.read_text(encoding="utf-8")
    updated = _regen_skill_md_text(skill_text)
    if updated != skill_text:
        atomic_write_text(SKILL_PATH, updated)


def check_skill_md_tools_count() -> bool:
    if not SKILL_PATH.exists():
        return False

    values = _extract_between_marker_pairs(
        SKILL_PATH.read_text(encoding="utf-8"),
        "<!-- TOOLS_COUNT_BEGIN -->",
        "<!-- TOOLS_COUNT_END -->",
    )
    drift = False
    expected = len(TOOL_CATALOG)
    for value in values:
        try:
            current = int(value)
        except ValueError:
            current = None
        if current != expected:
            drift = True
            print(
                f"Drift detected in SKILL.md tool count: current={value!r}, generated={expected}",
                file=sys.stderr,
            )
    return drift


def build_docs(tools: list) -> dict[Path, str]:
    docs = {}

    if SKILL_PATH.exists():
        skill_text = SKILL_PATH.read_text(encoding="utf-8")
        docs[SKILL_PATH] = _regen_skill_md_text(skill_text)

        tool_lines = "\n".join(
            f"- `{tool['name']}`: {tool['description']}" for tool in tools
        )
        updated = _replace_between_markers(
            skill_text,
            "<!-- TOOLS_LIST_START -->",
            "<!-- TOOLS_LIST_END -->",
            tool_lines,
        )
        if updated is not None:
            docs[SKILL_PATH] = _regen_skill_md_text(updated)

    if README_PATH.exists():
        readme_text = README_PATH.read_text(encoding="utf-8")
        marker = "<!-- TOOLS_COUNT -->"
        if marker in readme_text:
            docs[README_PATH] = readme_text.replace(marker, str(len(tools)))

    return docs


def _load_current_tools() -> object:
    try:
        return json.loads(TOOLS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None


def check_drift(tools: list, docs: dict[Path, str]) -> bool:
    drift = check_skill_md_tools_count()

    current_tools = _load_current_tools()
    if current_tools != tools:
        drift = True
        current_count = len(current_tools) if isinstance(current_tools, list) else "unreadable"
        print(
            f"Drift detected in tools.json: current={current_count}, generated={len(tools)}",
            file=sys.stderr,
        )

    for path, expected in docs.items():
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current != expected:
            drift = True
            print(f"Drift detected in {path.name}", file=sys.stderr)

    if not drift:
        print("No metadata drift detected", file=sys.stderr)
    return drift


def write_metadata(tools: list, docs: dict[Path, str]) -> None:
    atomic_write_json(TOOLS_PATH, tools)
    for path, content in docs.items():
        if path == SKILL_PATH:
            continue
        path.write_text(content, encoding="utf-8", newline="")
    regen_skill_md_placeholders()
    print(f"Wrote {len(tools)} tools to tools.json", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate tools.json and optional docs from cli.py TOOL_CATALOG."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate generated metadata against files without writing.",
    )
    args = parser.parse_args(argv)

    tools = build_tools()
    docs = build_docs(tools)
    if args.check:
        return 1 if check_drift(tools, docs) else 0

    write_metadata(tools, docs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
