# Architectural decisions (T0.4 / T0.5 / T0.6)

> Each decision is recorded once here and referenced by later iterations. Changes require explicit ADR-style amendment, not silent modification.

---

## Catalog format: `catalog.py` (Python module with typed dict literals) — T0.4

### Decision

The canonical tool catalog lives in `catalog.py` as a **module-level constant** of type `list[ToolDef]`, where `ToolDef` is a `TypedDict`. `tools.json` is a **derived artefact** generated from `catalog.py` via `scripts/regen_metadata.py`.

### Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **A. `catalog.py`** (chosen) | Single source of truth in code; type-checkable; can include callable defaults; trivial Python import; no extra parser | Less editor-friendly for non-Python users | ✅ chosen |
| B. `catalog.json` | Editor-friendly; auto-validated by JSON tools | Cannot have callable defaults; needs separate loader; risk of duplicating type info between JSON Schema and runtime types | rejected — adds parsing layer |
| C. Typed structure (e.g. dataclasses across multiple files) | Best for very large catalogs; supports inheritance/composition | Overkill for 63 tools; harder to scan in single review | rejected — premature |

### Rationale

- 63 tools fit comfortably in a single Python file (~600 lines, current `cli.py:395-1018` already does this).
- Generator (`regen_metadata.py`) produces `tools.json` for external consumers (Claude harness, IDEs).
- `--list` and `--describe` read directly from the in-memory list — no JSON round-trip at runtime.
- `TypedDict` gives mypy/pyright a chance to catch drift at edit time.

### Skeleton

```python
# catalog.py
from typing import TypedDict, Literal, NotRequired

ParamType = Literal["string", "integer", "number", "boolean", "array", "object"]

class ToolParam(TypedDict):
    type: ParamType
    description: NotRequired[str]
    enum: NotRequired[list[str]]
    items: NotRequired[dict]        # for type=array
    properties: NotRequired[dict]   # for type=object
    required: NotRequired[bool]

class ToolDef(TypedDict):
    name: str
    description: str
    category: Literal["task", "project", "tag", "habit", "kanban",
                      "note", "time", "derived", "cache", "meta"]
    parameters: dict[str, ToolParam]
    write: bool                     # marks write-side tool

TOOL_CATALOG: list[ToolDef] = [
    # ... 63 entries ...
]
```

### Consequences

- Iteration 4 generator script extracts JSON Schema-valid `tools.json` from this constant.
- Iteration 5 (`--describe`) reads from `TOOL_CATALOG` directly with type-mapping (`string` → `string` — already JSON Schema names; no Python→JSON Schema rename needed).
- README/SKILL.md placeholders `<!-- TOOLS_LIST -->` and `<!-- TOOLS_COUNT -->` regenerated from catalog.

---

## JSON Schema draft: `draft-07` — T0.5

### Decision

`--describe` output validates against [JSON Schema draft-07](https://json-schema.org/draft-07/schema). Reference validator: `jsonschema` lib (in `requirements-dev.txt`, not runtime).

### Alternatives considered

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **draft-07** (chosen) | Most widely supported; mature; works with all major validators | Doesn't have newest features (e.g. `unevaluatedProperties`) | ✅ chosen |
| draft 2019-09 | Adds `$defs`, `$anchor`, more keywords | Tooling support uneven | rejected |
| draft 2020-12 | Latest; aligned with OpenAPI 3.1 | Tooling support still spotty in 2026 for stdlib-friendly validators | rejected |

### Rationale

- This skill's tool schemas are simple: primitive types, arrays, nested objects with primitive properties. No advanced features needed.
- draft-07 is what most LLM tool-use systems (OpenAI function calling, Anthropic tool use) expect. Maximises consumer compatibility.
- `jsonschema` lib supports draft-07 natively in `Draft7Validator`.

### Type mapping (Python type-name → JSON Schema)

| Catalog type | JSON Schema `type` | Notes |
|---|---|---|
| `string` | `"string"` | identical |
| `integer` | `"integer"` | identical |
| `number` | `"number"` | float in catalog → number in schema |
| `boolean` | `"boolean"` | identical |
| `array` | `"array"` | requires `items` (a sub-schema) |
| `object` | `"object"` | requires `properties` (a dict of sub-schemas) |

**The catalog uses JSON Schema names directly.** No Python-to-JSON-Schema rename layer.

### Validation invariants

For every tool in `TOOL_CATALOG`:
1. `--describe <name>` produces a valid JSON Schema document under draft-07 meta-schema.
2. Every parameter with `type: "array"` has `items`.
3. Every parameter with `type: "object"` has `properties` (may be empty).
4. `enum` values are strings or numbers, never mixed.

Enforced by `tests/test_schema.py` (Iteration 4).

---

## Skill versioning: SemVer 2.0 — T0.6

### Decision

Skill carries a SemVer string in `catalog.py` as `SKILL_VERSION = "X.Y.Z"`. Bumped according to the rules below at the end of each iteration that changes external surface.

### Bump rules

| Change kind | Bump | Examples in this plan |
|---|---|---|
| **MAJOR** (breaking external contract) | `X+1.0.0` | Removing a tool; renaming a tool argument; changing return shape in incompatible way |
| **MINOR** (additive, backward compatible) | `X.Y+1.0` | Adding new fields to derived tools' return (Iter 1: `status`/`partial`/`note_status`/`warnings`); adding new optional argument; adding new tool; changing schema format from invalid → valid (Iter 4) |
| **PATCH** (internal, no user-visible change) | `X.Y.Z+1` | Modular refactor (Iter 6); silent-except cleanup (Iter 7); pagination internal change with same external semantics (Iter 2 partly) |

### Initial version

Current pre-iteration baseline: `SKILL_VERSION = "1.0.0"` (claimed; not yet present in code — added in T1.9 / T0.4 catalog skeleton).

### Bump schedule for this plan

| Iteration | End-of-iteration version | Bump kind |
|---|---|---|
| 0 (baseline) | `1.0.0` | initial — establish baseline |
| 1 (note correctness) | `1.1.0` | MINOR — additive response fields, fix bug |
| 2 (pagination) | `1.2.0` | MINOR — `partial: true` semantic added |
| 3 (cache) | `1.2.1` | PATCH — internal cache lifecycle, no user-visible API change |
| 4 (metadata/schema) | `1.3.0` | MINOR — schema format newly valid; tools.json includes derived tools |
| 5 (parity tests) | `1.3.1` | PATCH — only test infra |
| 6 (refactor) | `1.3.2` | PATCH — internal refactor; CLI parity guaranteed |
| 7 (hardening) | `1.4.0` | MINOR — new commands `--verify-api/--verify-cache/--verify-metadata`; `--doctor` aggregates them |
| 8 (backlog fixes) | `1.4.1` | PATCH — bugfixes |

### Consequences

- Every iteration commit must touch `SKILL_VERSION` if its bump rule says so.
- CHANGELOG.md gets one entry per version bump.
- `--list` and `--describe` outputs include version (machine-readable consumers can pin/upgrade).
- Verify in `tests/test_cli_parity.py`: snapshot includes version string; regen on bump is intentional and explained in commit message.
