"""Config loading for singularity skill (Iter 6 / T6.3).

This module is the ONLY place that reads or writes `config.json` (per
secrets-policy.md). Cache layer must NOT touch config — see T3.9.

Schema:
    {
      "base_url": "https://api.singularity-app.com",
      "token": "<bearer>",
      "read_only": false,
      "cache_ttl_days": 30
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load config.json, raise FileNotFoundError with helpful message if missing."""
    cfg_path = Path(path) if path else CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"config.json not found at {cfg_path}. "
            "Create it with at least: "
            '{"base_url": "https://api.singularity-app.com", "token": "..."}'
        )
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def is_read_only(cfg: dict) -> bool:
    return bool(cfg.get("read_only", False))


def cache_ttl_days(cfg: dict, default: int = 30) -> int:
    return int(cfg.get("cache_ttl_days", default))


__all__ = [
    "ROOT",
    "CONFIG_PATH",
    "load_config",
    "is_read_only",
    "cache_ttl_days",
]
