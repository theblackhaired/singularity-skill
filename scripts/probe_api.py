#!/usr/bin/env python3
"""Iteration 0 — T0.1 + T0.2 — probe live API to fixate observed shapes.

Calls (read-only):
  1. GET /v2/task?maxCount=5         -- pick a task with non-empty note
  2. GET /v2/note?containerId=<id>   -- shape of /v2/note (if endpoint exists)
  3. GET /v2/task/{id}               -- check if `note` is embedded by default
  4. GET /v2/task/{id}?expand=note   -- check `expand=note` variant

Output: references/contract/observed-api-shapes.json
        (fields redacted: token never written; user-content collapsed to types)
"""

import json
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import ssl

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
BASE = CFG["base_url"].rstrip("/")
TOKEN = CFG["token"]
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}
CTX = ssl.create_default_context()


def call(method, path, params=None):
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=HEADERS, method=method)
    try:
        with urlopen(req, context=CTX, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return e.code, {"_error": body[:500]}
    except Exception as e:
        return -1, {"_error": str(e)[:500]}


def shape(value, depth=0):
    """Recursively replace primitives with their type names; structure preserved."""
    if depth > 6:
        return "<...>"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        if not value:
            return ["<empty>"]
        # Sample shape of first element only
        return [shape(value[0], depth + 1), f"<{len(value)} items>"]
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in value.items()}
    return f"<unknown:{type(value).__name__}>"


def main():
    out = {
        "_meta": {
            "purpose": "Iteration 0 baseline — observed API shapes (redacted)",
            "redaction": "tokens omitted; user content replaced by JSON Schema-style types",
            "base_url": BASE,
        },
        "endpoints": {},
    }

    # Step 1: get a task list to pick a candidate task
    print("[1/4] GET /v2/task?maxCount=5 ...", file=sys.stderr)
    status, body = call("GET", "/v2/task", {"maxCount": 5})
    out["endpoints"]["GET /v2/task"] = {
        "status": status,
        "shape": shape(body) if isinstance(body, (dict, list)) else None,
    }

    # Pick task_id and a task that potentially has note
    task_id = None
    if isinstance(body, dict):
        tasks = body.get("tasks") or body.get("content") or []
        if tasks:
            task_id = tasks[0].get("id")
    elif isinstance(body, list) and body:
        task_id = body[0].get("id")

    if not task_id:
        print("[!] Could not pick task_id; aborting note probes", file=sys.stderr)
        out["_meta"]["task_id_acquired"] = False
    else:
        out["_meta"]["task_id_acquired"] = True

        # Step 2: probe /v2/note
        print(f"[2/4] GET /v2/note?containerId=<id>&maxCount=1 ...", file=sys.stderr)
        status, body = call("GET", "/v2/note",
                             {"containerId": task_id, "maxCount": 1})
        out["endpoints"]["GET /v2/note"] = {
            "status": status,
            "shape": shape(body) if body is not None else None,
            "wrapper_keys": list(body.keys()) if isinstance(body, dict) else None,
        }

        # Step 3: GET /v2/task/{id} (no expand)
        print(f"[3/4] GET /v2/task/{{id}} (no expand) ...", file=sys.stderr)
        status, body = call("GET", f"/v2/task/{task_id}")
        note_present = False
        note_shape = None
        if isinstance(body, dict):
            note_present = "note" in body
            if note_present:
                note_shape = shape(body["note"])
        out["endpoints"]["GET /v2/task/{id}"] = {
            "status": status,
            "note_field_presence": "always" if note_present else "absent",
            "note_shape": note_shape,
            "shape": shape(body) if body is not None else None,
        }

        # Step 4: GET /v2/task/{id}?expand=note
        print(f"[4/4] GET /v2/task/{{id}}?expand=note ...", file=sys.stderr)
        status, body = call("GET", f"/v2/task/{task_id}", {"expand": "note"})
        note_present_expand = False
        note_shape_expand = None
        if isinstance(body, dict):
            note_present_expand = "note" in body and body["note"] is not None
            if "note" in body:
                note_shape_expand = shape(body["note"])
        out["endpoints"]["GET /v2/task/{id}?expand=note"] = {
            "status": status,
            "note_field_presence": "with_expand" if note_present_expand else "absent",
            "note_shape": note_shape_expand,
            "shape": shape(body) if body is not None else None,
        }

    # Decision summary
    out["_meta"]["decision_input"] = {
        "v2_note_endpoint_works": (
            out["endpoints"].get("GET /v2/note", {}).get("status") == 200
        ),
        "v2_note_wrapper_keys": (
            out["endpoints"].get("GET /v2/note", {}).get("wrapper_keys")
        ),
        "task_has_note_default": (
            out["endpoints"].get("GET /v2/task/{id}", {})
                            .get("note_field_presence") == "always"
        ),
        "task_has_note_with_expand": (
            out["endpoints"].get("GET /v2/task/{id}?expand=note", {})
                            .get("note_field_presence") == "with_expand"
        ),
    }

    out_dir = ROOT / "references" / "contract"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "observed-api-shapes.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\nWrote {out_path}")
    print("\n=== Decision input ===")
    print(json.dumps(out["_meta"]["decision_input"], indent=2))


if __name__ == "__main__":
    main()
