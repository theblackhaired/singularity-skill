"""Self-check runner for singularity skill (Iter 6 / T6.9).

Implements `--doctor` command logic: 8 read-only sanity checks.
**ZERO side effects** — verified by tests/test_cli_parity::test_doctor_no_side_effects
and tests/test_config_safety.

Public API:
    doctor_run(skill_version: str, timeout: int = 10) -> dict

Returns:
    {"status": "ok"|"fail", "skill_version": str,
     "checks": [{"name", "status", "detail"}, ...],
     "summary": "N/M checks passed"}
"""

from __future__ import annotations

import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent


def doctor_run(skill_version: str = "unknown", timeout: int = 10) -> dict:
    """T0.13 — read-only self-check; ZERO side effects.

    Performs:
      1. config.json exists and parses
      2. .gitignore lists config.json
      3. base_url reachable (HTTP)
      4. /v2/api-json returns valid OpenAPI 3 JSON
      5. /v2/note capability (wrapper 'notes' present)
      6. cache files readable (if exist)
      7. observed-api-shapes.json exists (post-T0.1 baseline)

    Returns dict {status, skill_version, checks: [...]}; never writes.
    """
    checks = []

    def add(name, ok, detail=""):
        checks.append({
            "name": name,
            "status": "ok" if ok else "fail",
            "detail": detail,
        })

    # C1. config.json exists and parseable
    cfg_path = ROOT / "config.json"
    cfg = None
    if not cfg_path.exists():
        add("config_exists", False,
            f"config.json missing at {cfg_path}; create one with base_url+token")
    else:
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            add("config_exists", True, "config.json found and valid JSON")
        except json.JSONDecodeError as exc:
            add("config_exists", False, f"invalid JSON: {exc}")

    # C2. config.json in .gitignore
    gitignore = ROOT / ".gitignore"
    if gitignore.exists():
        gi_text = gitignore.read_text(encoding="utf-8")
        in_gi = any(
            line.strip() == "config.json"
            for line in gi_text.splitlines()
        )
        add("config_gitignored", in_gi,
            "config.json listed in .gitignore" if in_gi
            else "WARNING: config.json NOT in .gitignore — token may leak")
    else:
        add("config_gitignored", False, ".gitignore missing")

    # Stop further checks if config not loaded — they all need base_url/token
    if cfg is None:
        return {
            "status": "fail",
            "skill_version": skill_version,
            "checks": checks,
            "summary": "config.json missing or invalid; cannot run live checks",
        }

    base_url = cfg.get("base_url", "").rstrip("/")
    token = cfg.get("token", "")
    if not base_url or not token:
        add("config_fields", False,
            "config.json missing base_url or token field")
        return {
            "status": "fail",
            "skill_version": skill_version,
            "checks": checks,
            "summary": "config.json incomplete",
        }
    add("config_fields", True, "base_url and token present")

    # Probe helper (read-only, short timeout)
    ctx = ssl.create_default_context()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    def probe(path, params=None):
        url = base_url + path
        if params:
            url += "?" + urlencode(params)
        try:
            req = Request(url, headers=headers, method="GET")
            with urlopen(req, context=ctx, timeout=timeout) as r:
                raw = r.read()
                return r.status, raw
        except HTTPError as e:
            return e.code, None
        except URLError as e:
            return -1, str(e.reason).encode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001 — doctor must never crash
            return -2, str(e).encode("utf-8", errors="replace")

    # C3. base_url reachable (HEAD-equivalent via /v2/api-json HEAD-ish)
    status, _ = probe("/v2/api-json")
    add("base_url_reachable", status == 200,
        f"GET {base_url}/v2/api-json -> HTTP {status}")

    # C4. /v2/api-json returns OpenAPI document
    if status == 200:
        status2, body = probe("/v2/api-json")
        try:
            doc = json.loads(body.decode("utf-8")) if body else {}
            is_openapi = isinstance(doc, dict) and (
                "openapi" in doc or "swagger" in doc
            )
            version = doc.get("openapi") or doc.get("swagger") or "unknown"
            add("openapi_v2_available", is_openapi,
                f"/v2/api-json returns OpenAPI {version}" if is_openapi
                else "/v2/api-json did not return OpenAPI document")
        except (json.JSONDecodeError, AttributeError, UnicodeDecodeError) as exc:
            add("openapi_v2_available", False,
                f"could not parse OpenAPI response: {exc}")
    else:
        add("openapi_v2_available", False,
            f"skipped — base_url unreachable (HTTP {status})")

    # C5. /v2/note capability
    status_a, _ = probe("/v2/note", {"maxCount": 0})
    if status_a == 404:
        add("v2_note_capability", False,
            "GET /v2/note -> HTTP 404 (endpoint does not exist)")
    else:
        status_t, body_t = probe("/v2/task", {"maxCount": 1})
        cid = None
        if status_t == 200 and body_t:
            try:
                tdoc = json.loads(body_t.decode("utf-8"))
                tasks = tdoc.get("tasks") if isinstance(tdoc, dict) else None
                if tasks:
                    cid = tasks[0].get("id")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        if cid is None:
            add("v2_note_capability", True,
                f"GET /v2/note -> HTTP {status_a} (endpoint alive; "
                f"shape not verified — no tasks available)")
        else:
            status_b, body_b = probe("/v2/note",
                                       {"containerId": cid, "maxCount": 1})
            if status_b == 200 and body_b:
                try:
                    ndoc = json.loads(body_b.decode("utf-8"))
                    ok = isinstance(ndoc, dict) and "notes" in ndoc \
                         and isinstance(ndoc["notes"], list)
                    add("v2_note_capability", ok,
                        "GET /v2/note returns wrapper 'notes' (capability OK)" if ok
                        else f"GET /v2/note returned unexpected shape: "
                             f"keys={list(ndoc.keys()) if isinstance(ndoc, dict) else type(ndoc).__name__}")
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    add("v2_note_capability", False,
                        f"could not parse /v2/note response: {exc}")
            else:
                add("v2_note_capability", False,
                    f"GET /v2/note?containerId=... -> HTTP {status_b}")

    # C6. cache files readable
    refs_dir = ROOT / "references"
    cache_files = ["projects.json", "tags.json", "task_groups.json"]
    cache_state = []
    for fname in cache_files:
        fpath = refs_dir / fname
        if not fpath.exists():
            cache_state.append(f"{fname}=missing")
            continue
        try:
            json.loads(fpath.read_text(encoding="utf-8"))
            cache_state.append(f"{fname}=ok")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            cache_state.append(f"{fname}=corrupted({exc})")
    cache_ok = all(s.endswith("=ok") or s.endswith("=missing")
                   for s in cache_state)
    add("cache_files_readable", cache_ok, "; ".join(cache_state))

    # C7. observed-api-shapes.json baseline
    obs_path = ROOT / "references" / "contract" / "observed-api-shapes.json"
    add("contract_baseline_exists", obs_path.exists(),
        f"baseline at {obs_path.relative_to(ROOT)}" if obs_path.exists()
        else "missing — run scripts/probe_api.py to regenerate (T0.1+T0.2)")

    overall = "ok" if all(c["status"] == "ok" for c in checks) else "fail"
    return {
        "status": overall,
        "skill_version": skill_version,
        "checks": checks,
        "summary": f"{sum(1 for c in checks if c['status']=='ok')}/{len(checks)} checks passed",
    }


__all__ = ["doctor_run"]
