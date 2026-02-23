#!/usr/bin/env python3
"""Singularity App Skill CLI -- direct REST API client for task management.

Usage:
  python cli.py --list
  python cli.py --describe project_list
  python cli.py --call '{"tool":"project_list","arguments":{}}'

Python 3.8+ stdlib only (urllib, json, ssl). Bearer token auth.
"""

import argparse
import json
import sys
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
REFS_DIR = ROOT / "references"

# ---------------------------------------------------------------------------
# HTTP Client
# ---------------------------------------------------------------------------

class SingularityClient:
    """Low-level HTTP client with Bearer auth, SSL context and retry."""

    RETRYABLE_CODES = {429, 500, 502, 503, 504}

    def __init__(self, base_url: str, token: str,
                 max_retries: int = 3, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.max_retries = max_retries
        self.timeout = timeout

        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        self._ssl_ctx = ssl.create_default_context()

    # -- internal ----------------------------------------------------------

    def _request(self, method: str, path: str, params: dict = None,
                 body: dict = None):
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urlencode(clean)

        data = json.dumps(body).encode("utf-8") if body is not None else None

        for attempt in range(1, self.max_retries + 1):
            try:
                req = Request(url, data=data, headers=self._headers,
                              method=method)
                with urlopen(req, context=self._ssl_ctx,
                             timeout=self.timeout) as resp:
                    raw = resp.read()
                    if not raw:
                        return {}
                    return json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                if exc.code in self.RETRYABLE_CODES and attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)
                    print(f"HTTP {exc.code}, retry in {delay}s "
                          f"({attempt}/{self.max_retries})...",
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
                err_body = ""
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass
                # Try to parse Singularity error format {errors:[{code,message}]}
                try:
                    err_json = json.loads(err_body)
                    errors = err_json.get("errors", [])
                    if errors:
                        msgs = "; ".join(
                            f"[{e.get('code','')}] {e.get('message','')}"
                            for e in errors
                        )
                        raise RuntimeError(
                            f"HTTP {exc.code} on {method} {url}: {msgs}"
                        ) from exc
                except (json.JSONDecodeError, AttributeError):
                    pass
                raise RuntimeError(
                    f"HTTP {exc.code} {exc.reason} on {method} {url}\n"
                    f"{err_body}"
                ) from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)
                    print(f"Network error, retry in {delay}s "
                          f"({attempt}/{self.max_retries})...",
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise

    # -- public verbs -------------------------------------------------------

    def get(self, path: str, params: dict = None):
        return self._request("GET", path, params=params)

    def post(self, path: str, data: dict = None):
        return self._request("POST", path, body=data)

    def patch(self, path: str, data: dict = None):
        return self._request("PATCH", path, body=data)

    def delete(self, path: str, params: dict = None):
        return self._request("DELETE", path, params=params)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"config.json not found in {ROOT}")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Resource definitions (data-driven CRUD)
# ---------------------------------------------------------------------------
# Each resource: path, list_params, body_fields
# list_params: {api_param: (arg_name, type, default)}
# body_fields: [field_name, ...]  -- fields accepted in create/update body

RESOURCES = {
    "project": {
        "path": "/v2/project",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "includeRemoved": ("include_removed", "bool", None),
            "includeArchived": ("include_archived", "bool", None),
        },
        "body_fields": [
            "title", "note", "start", "end", "emoji", "color", "parent",
            "parentOrder", "isNotebook", "tags", "showInBasket", "deleteDate",
            "externalId", "reviewValidationDate", "reviewValidationInterval",
            "journalDate",
        ],
    },
    "task_group": {
        "path": "/v2/task-group",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "includeRemoved": ("include_removed", "bool", None),
            "parent": ("parent", "str", None),
        },
        "body_fields": [
            "title", "parent", "parentOrder", "fake", "externalId",
        ],
    },
    "task": {
        "path": "/v2/task",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "includeRemoved": ("include_removed", "bool", None),
            "includeArchived": ("include_archived", "bool", None),
            "includeAllRecurrenceInstances": (
                "include_all_recurrence_instances", "bool", None),
            "projectId": ("project_id", "str", None),
            "parent": ("parent", "str", None),
            "startDateFrom": ("start_date_from", "str", None),
            "startDateTo": ("start_date_to", "str", None),
        },
        "body_fields": [
            "title", "note", "priority", "start", "useTime", "deadline",
            "parent", "tags", "complete", "completeLast", "state", "checked",
            "showInBasket", "projectId", "recurrence", "journalDate",
            "isNote", "notify", "notifies", "alarmNotify", "externalId",
        ],
    },
    "note": {
        "path": "/v2/note",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "containerId": ("container_id", "str", None),
        },
        "body_fields": [
            "containerId", "content", "contentType", "externalId",
        ],
    },
    "kanban_status": {
        "path": "/v2/kanban-status",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "includeRemoved": ("include_removed", "bool", None),
            "projectId": ("project_id", "str", None),
        },
        "body_fields": [
            "name", "projectId", "kanbanOrder", "numberOfColumns",
            "externalId",
        ],
    },
    "kanban_task_status": {
        "path": "/v2/kanban-task-status",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "includeRemoved": ("include_removed", "bool", None),
            "taskId": ("task_id", "str", None),
            "statusId": ("status_id", "str", None),
        },
        "body_fields": [
            "taskId", "statusId", "kanbanOrder", "externalId",
        ],
    },
    "habit": {
        "path": "/v2/habit",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
        },
        "body_fields": [
            "title", "description", "color", "order", "status",
            "externalId",
        ],
    },
    "habit_progress": {
        "path": "/v2/habit-progress",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "habit": ("habit", "str", None),
            "startDate": ("start_date", "str", None),
            "endDate": ("end_date", "str", None),
        },
        "body_fields": [
            "habit", "date", "progress", "externalId",
        ],
    },
    "checklist": {
        "path": "/v2/checklist-item",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "includeRemoved": ("include_removed", "bool", None),
            "parent": ("parent", "str", None),
        },
        "body_fields": [
            "parent", "title", "done", "crypted", "parentOrder",
        ],
    },
    "tag": {
        "path": "/v2/tag",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "includeRemoved": ("include_removed", "bool", None),
            "parent": ("parent", "str", None),
        },
        "body_fields": [
            "title", "color", "hotkey", "parent", "parentOrder",
            "externalId",
        ],
    },
    "time_stat": {
        "path": "/v2/time-stat",
        "list_params": {
            "maxCount": ("max_count", "int", 100),
            "offset": ("offset", "int", None),
            "dateFrom": ("date_from", "str", None),
            "dateTo": ("date_to", "str", None),
            "relatedTaskId": ("related_task_id", "str", None),
        },
        "body_fields": [
            "start", "secondsPassed", "relatedTaskId", "source",
        ],
    },
}


# ---------------------------------------------------------------------------
# Generic CRUD handlers
# ---------------------------------------------------------------------------

def _coerce(value, type_str: str):
    """Coerce a value to the expected API type."""
    if value is None:
        return None
    if type_str == "int":
        return int(value)
    if type_str == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")
        return bool(value)
    return str(value)


def _list_handler(client: SingularityClient, res_key: str,
                  args: dict) -> dict:
    res = RESOURCES[res_key]
    params = {}
    for api_param, (arg_name, ptype, default) in res["list_params"].items():
        val = args.get(arg_name, default)
        if val is not None:
            val = _coerce(val, ptype)
            # Convert Python bools to lowercase string for query params
            if isinstance(val, bool):
                val = str(val).lower()
            params[api_param] = val
    return client.get(res["path"], params)


def _get_handler(client: SingularityClient, res_key: str,
                 args: dict) -> dict:
    res = RESOURCES[res_key]
    entity_id = args.get("id")
    if not entity_id:
        raise ValueError("id is required")
    return client.get(f"{res['path']}/{quote(str(entity_id))}")


def _create_handler(client: SingularityClient, res_key: str,
                    args: dict) -> dict:
    res = RESOURCES[res_key]
    body = {}
    for field in res["body_fields"]:
        if field in args:
            body[field] = args[field]
    return client.post(res["path"], body)


def _update_handler(client: SingularityClient, res_key: str,
                    args: dict) -> dict:
    res = RESOURCES[res_key]
    entity_id = args.get("id")
    if not entity_id:
        raise ValueError("id is required")
    body = {}
    for field in res["body_fields"]:
        if field in args:
            body[field] = args[field]
    if not body:
        raise ValueError("At least one field to update is required")
    return client.patch(f"{res['path']}/{quote(str(entity_id))}", body)


def _delete_handler(client: SingularityClient, res_key: str,
                    args: dict) -> dict:
    res = RESOURCES[res_key]
    entity_id = args.get("id")
    if not entity_id:
        raise ValueError("id is required")
    result = client.delete(f"{res['path']}/{quote(str(entity_id))}")
    return result if result else {"success": True}


def _time_stat_bulk_delete_handler(client: SingularityClient, res_key: str,
                                   args: dict) -> dict:
    params = {}
    if "date_from" in args:
        params["dateFrom"] = args["date_from"]
    if "date_to" in args:
        params["dateTo"] = args["date_to"]
    if "related_task_id" in args:
        params["relatedTaskId"] = args["related_task_id"]
    result = client.delete("/v2/time-stat", params=params)
    return result if result else {"success": True}


# ---------------------------------------------------------------------------
# Tool Catalog (for --list / --describe)
# ---------------------------------------------------------------------------

TOOL_CATALOG = {
    # --- Projects ---
    "project_list": {
        "desc": "List projects",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results (<=1000)"},
            "offset": {"type": "int", "desc": "Pagination offset (>=0)"},
            "include_removed": {"type": "bool", "desc": "Include removed projects"},
            "include_archived": {"type": "bool", "desc": "Include archived projects"},
        },
    },
    "project_get": {
        "desc": "Get project by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Project ID"},
        },
    },
    "project_create": {
        "desc": "Create project",
        "params": {
            "title": {"type": "str", "required": True, "desc": "Project title"},
            "note": {"type": "str", "desc": "Project description"},
            "start": {"type": "str", "desc": "Start date ISO"},
            "end": {"type": "str", "desc": "End date ISO"},
            "emoji": {"type": "str", "desc": "Emoji hex code (e.g. 1f49e)"},
            "color": {"type": "str", "desc": "Color value"},
            "parent": {"type": "str", "desc": "Parent project ID"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
            "isNotebook": {"type": "bool", "desc": "Create as notebook"},
            "tags": {"type": "list", "desc": "Tag IDs array"},
            "showInBasket": {"type": "bool", "desc": "Show in basket"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "project_update": {
        "desc": "Update project",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Project ID"},
            "title": {"type": "str", "desc": "Project title"},
            "note": {"type": "str", "desc": "Project description"},
            "start": {"type": "str", "desc": "Start date ISO"},
            "end": {"type": "str", "desc": "End date ISO"},
            "emoji": {"type": "str", "desc": "Emoji hex code (e.g. 1f49e)"},
            "color": {"type": "str", "desc": "Color value"},
            "parent": {"type": "str", "desc": "Parent project ID"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
            "isNotebook": {"type": "bool", "desc": "Notebook flag"},
            "tags": {"type": "list", "desc": "Tag IDs array"},
            "showInBasket": {"type": "bool", "desc": "Show in basket"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "project_delete": {
        "desc": "Delete project",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Project ID"},
        },
    },

    # --- Task Groups ---
    "task_group_list": {
        "desc": "List task groups",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "include_removed": {"type": "bool", "desc": "Include removed"},
            "parent": {"type": "str", "desc": "Parent project ID (P-uuid format)"},
        },
    },
    "task_group_get": {
        "desc": "Get task group by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Task group ID"},
        },
    },
    "task_group_create": {
        "desc": "Create task group",
        "params": {
            "title": {"type": "str", "required": True, "desc": "Group title"},
            "parent": {"type": "str", "required": True, "desc": "Parent project ID (P-uuid)"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
            "fake": {"type": "bool", "desc": "Fake group flag"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "task_group_update": {
        "desc": "Update task group",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Task group ID"},
            "title": {"type": "str", "desc": "Group title"},
            "parent": {"type": "str", "desc": "Parent project ID"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
            "fake": {"type": "bool", "desc": "Fake group flag"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "task_group_delete": {
        "desc": "Delete task group",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Task group ID"},
        },
    },

    # --- Tasks ---
    "task_list": {
        "desc": "List tasks",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results (<=1000)"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "include_removed": {"type": "bool", "desc": "Include removed"},
            "include_archived": {"type": "bool", "desc": "Include archived"},
            "include_all_recurrence_instances": {"type": "bool", "desc": "Include all recurrence instances"},
            "project_id": {"type": "str", "desc": "Filter by project ID"},
            "parent": {"type": "str", "desc": "Filter by parent task group ID"},
            "start_date_from": {"type": "str", "desc": "Start date from (ISO)"},
            "start_date_to": {"type": "str", "desc": "Start date to (ISO)"},
        },
    },
    "task_get": {
        "desc": "Get task by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Task ID"},
        },
    },
    "task_create": {
        "desc": "Create task",
        "params": {
            "title": {"type": "str", "required": True, "desc": "Task title"},
            "parent": {"type": "str", "required": True, "desc": "Task group ID (parent)"},
            "note": {"type": "str", "desc": "Task description"},
            "priority": {"type": "int", "desc": "Priority (default 1)"},
            "start": {"type": "str", "desc": "Start datetime ISO"},
            "useTime": {"type": "bool", "desc": "false=date only, true=real time GMT+3"},
            "deadline": {"type": "str", "desc": "Deadline datetime ISO"},
            "tags": {"type": "list", "desc": "Tag IDs array"},
            "complete": {"type": "str", "desc": "Completion datetime ISO"},
            "completeLast": {"type": "str", "desc": "Last completion datetime"},
            "state": {"type": "str", "desc": "Task state"},
            "checked": {"type": "bool", "desc": "Checked flag"},
            "showInBasket": {"type": "bool", "desc": "Show in basket"},
            "projectId": {"type": "str", "desc": "Project ID"},
            "recurrence": {"type": "object", "desc": "Recurrence config"},
            "journalDate": {"type": "str", "desc": "Journal date ISO"},
            "isNote": {"type": "bool", "desc": "Note in notebook flag"},
            "notify": {"type": "int", "desc": "Notification flag (0 or 1)"},
            "notifies": {"type": "list", "desc": "Notification minutes array e.g. [60,15]"},
            "alarmNotify": {"type": "bool", "desc": "Alarm notification"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "task_update": {
        "desc": "Update task",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Task ID"},
            "title": {"type": "str", "desc": "Task title"},
            "note": {"type": "str", "desc": "Task description"},
            "priority": {"type": "int", "desc": "Priority"},
            "start": {"type": "str", "desc": "Start datetime ISO"},
            "useTime": {"type": "bool", "desc": "false=date only, true=real time GMT+3"},
            "deadline": {"type": "str", "desc": "Deadline datetime ISO"},
            "parent": {"type": "str", "desc": "Task group ID"},
            "tags": {"type": "list", "desc": "Tag IDs array"},
            "complete": {"type": "str", "desc": "Completion datetime ISO"},
            "completeLast": {"type": "str", "desc": "Last completion datetime"},
            "state": {"type": "str", "desc": "Task state"},
            "checked": {"type": "bool", "desc": "Checked flag"},
            "showInBasket": {"type": "bool", "desc": "Show in basket"},
            "projectId": {"type": "str", "desc": "Project ID"},
            "recurrence": {"type": "object", "desc": "Recurrence config"},
            "journalDate": {"type": "str", "desc": "Journal date ISO"},
            "isNote": {"type": "bool", "desc": "Note in notebook flag"},
            "notify": {"type": "int", "desc": "Notification flag (0 or 1)"},
            "notifies": {"type": "list", "desc": "Notification minutes array"},
            "alarmNotify": {"type": "bool", "desc": "Alarm notification"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "task_delete": {
        "desc": "Delete task",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Task ID"},
        },
    },

    # --- Notes ---
    "note_list": {
        "desc": "List notes",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "container_id": {"type": "str", "desc": "Container (project/task) ID"},
        },
    },
    "note_get": {
        "desc": "Get note by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Note ID"},
        },
    },
    "note_create": {
        "desc": "Create note",
        "params": {
            "containerId": {"type": "str", "required": True, "desc": "Container (project/task) ID"},
            "content": {"type": "list", "required": True, "desc": "Delta array [{insert:...},...] -- last insert must end with newline"},
            "contentType": {"type": "str", "default": "delta", "desc": "Content type (always 'delta')"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "note_update": {
        "desc": "Update note",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Note ID"},
            "containerId": {"type": "str", "desc": "Container ID"},
            "content": {"type": "list", "desc": "Delta array"},
            "contentType": {"type": "str", "desc": "Content type"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "note_delete": {
        "desc": "Delete note",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Note ID"},
        },
    },

    # --- Kanban Statuses ---
    "kanban_status_list": {
        "desc": "List kanban statuses",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "include_removed": {"type": "bool", "desc": "Include removed"},
            "project_id": {"type": "str", "desc": "Filter by project ID"},
        },
    },
    "kanban_status_get": {
        "desc": "Get kanban status by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Kanban status ID"},
        },
    },
    "kanban_status_create": {
        "desc": "Create kanban status",
        "params": {
            "name": {"type": "str", "required": True, "desc": "Status name"},
            "projectId": {"type": "str", "required": True, "desc": "Project ID"},
            "kanbanOrder": {"type": "int", "desc": "Order position"},
            "numberOfColumns": {"type": "int", "desc": "Number of columns"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "kanban_status_update": {
        "desc": "Update kanban status",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Kanban status ID"},
            "name": {"type": "str", "desc": "Status name"},
            "projectId": {"type": "str", "desc": "Project ID"},
            "kanbanOrder": {"type": "int", "desc": "Order position"},
            "numberOfColumns": {"type": "int", "desc": "Number of columns"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "kanban_status_delete": {
        "desc": "Delete kanban status",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Kanban status ID"},
        },
    },

    # --- Kanban Task Statuses ---
    "kanban_task_status_list": {
        "desc": "List kanban task statuses",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "include_removed": {"type": "bool", "desc": "Include removed"},
            "task_id": {"type": "str", "desc": "Filter by task ID"},
            "status_id": {"type": "str", "desc": "Filter by status ID"},
        },
    },
    "kanban_task_status_get": {
        "desc": "Get kanban task status by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Kanban task status ID"},
        },
    },
    "kanban_task_status_create": {
        "desc": "Create kanban task status",
        "params": {
            "taskId": {"type": "str", "required": True, "desc": "Task ID"},
            "statusId": {"type": "str", "required": True, "desc": "Kanban status ID"},
            "kanbanOrder": {"type": "int", "desc": "Order position"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "kanban_task_status_update": {
        "desc": "Update kanban task status",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Kanban task status ID"},
            "taskId": {"type": "str", "desc": "Task ID"},
            "statusId": {"type": "str", "desc": "Kanban status ID"},
            "kanbanOrder": {"type": "int", "desc": "Order position"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "kanban_task_status_delete": {
        "desc": "Delete kanban task status",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Kanban task status ID"},
        },
    },

    # --- Habits ---
    "habit_list": {
        "desc": "List habits",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
        },
    },
    "habit_get": {
        "desc": "Get habit by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Habit ID"},
        },
    },
    "habit_create": {
        "desc": "Create habit",
        "params": {
            "title": {"type": "str", "required": True, "desc": "Habit title"},
            "description": {"type": "str", "desc": "Habit description"},
            "color": {"type": "str", "desc": "Color enum: red|pink|purple|deepPurple|indigo|lightBlue|cyan|teal|green|lightGreen|lime|yellow|amber|orange|deepOrange|brown|grey|blueGrey"},
            "order": {"type": "int", "desc": "Display order"},
            "status": {"type": "int", "desc": "0=active, 1=paused, 2=completed, 3=archived"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "habit_update": {
        "desc": "Update habit",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Habit ID"},
            "title": {"type": "str", "desc": "Habit title"},
            "description": {"type": "str", "desc": "Habit description"},
            "color": {"type": "str", "desc": "Color enum"},
            "order": {"type": "int", "desc": "Display order"},
            "status": {"type": "int", "desc": "0=active, 1=paused, 2=completed, 3=archived"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "habit_delete": {
        "desc": "Delete habit",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Habit ID"},
        },
    },

    # --- Habit Progress ---
    "habit_progress_list": {
        "desc": "List habit progress entries",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "habit": {"type": "str", "desc": "Habit ID"},
            "start_date": {"type": "str", "desc": "Start date ISO"},
            "end_date": {"type": "str", "desc": "End date ISO"},
        },
    },
    "habit_progress_get": {
        "desc": "Get habit progress entry by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Habit progress ID"},
        },
    },
    "habit_progress_create": {
        "desc": "Create habit progress entry",
        "params": {
            "habit": {"type": "str", "required": True, "desc": "Habit ID"},
            "date": {"type": "str", "required": True, "desc": "Date ISO"},
            "progress": {"type": "float", "required": True, "desc": "Progress value (number)"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "habit_progress_update": {
        "desc": "Update habit progress entry",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Habit progress ID"},
            "habit": {"type": "str", "desc": "Habit ID"},
            "date": {"type": "str", "desc": "Date ISO"},
            "progress": {"type": "float", "desc": "Progress value"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "habit_progress_delete": {
        "desc": "Delete habit progress entry",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Habit progress ID"},
        },
    },

    # --- Checklist Items ---
    "checklist_list": {
        "desc": "List checklist items",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "include_removed": {"type": "bool", "desc": "Include removed"},
            "parent": {"type": "str", "desc": "Parent task ID"},
        },
    },
    "checklist_get": {
        "desc": "Get checklist item by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Checklist item ID"},
        },
    },
    "checklist_create": {
        "desc": "Create checklist item",
        "params": {
            "parent": {"type": "str", "required": True, "desc": "Parent task ID"},
            "title": {"type": "str", "required": True, "desc": "Item title"},
            "done": {"type": "bool", "desc": "Completion state"},
            "crypted": {"type": "bool", "desc": "Encrypted flag"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
        },
    },
    "checklist_update": {
        "desc": "Update checklist item",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Checklist item ID"},
            "parent": {"type": "str", "desc": "Parent task ID"},
            "title": {"type": "str", "desc": "Item title"},
            "done": {"type": "bool", "desc": "Completion state"},
            "crypted": {"type": "bool", "desc": "Encrypted flag"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
        },
    },
    "checklist_delete": {
        "desc": "Delete checklist item",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Checklist item ID"},
        },
    },

    # --- Tags ---
    "tag_list": {
        "desc": "List tags",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "include_removed": {"type": "bool", "desc": "Include removed"},
            "parent": {"type": "str", "desc": "Parent tag ID"},
        },
    },
    "tag_get": {
        "desc": "Get tag by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Tag ID"},
        },
    },
    "tag_create": {
        "desc": "Create tag",
        "params": {
            "title": {"type": "str", "required": True, "desc": "Tag title"},
            "color": {"type": "str", "desc": "Tag color"},
            "hotkey": {"type": "str", "desc": "Keyboard shortcut"},
            "parent": {"type": "str", "desc": "Parent tag ID"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "tag_update": {
        "desc": "Update tag",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Tag ID"},
            "title": {"type": "str", "desc": "Tag title"},
            "color": {"type": "str", "desc": "Tag color"},
            "hotkey": {"type": "str", "desc": "Keyboard shortcut"},
            "parent": {"type": "str", "desc": "Parent tag ID"},
            "parentOrder": {"type": "int", "desc": "Order within parent"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "tag_delete": {
        "desc": "Delete tag",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Tag ID"},
        },
    },

    # --- Time Stats ---
    "time_stat_list": {
        "desc": "List time tracking entries",
        "params": {
            "max_count": {"type": "int", "default": 100, "desc": "Max results"},
            "offset": {"type": "int", "desc": "Pagination offset"},
            "date_from": {"type": "str", "desc": "Date from ISO"},
            "date_to": {"type": "str", "desc": "Date to ISO"},
            "related_task_id": {"type": "str", "desc": "Filter by task ID"},
        },
    },
    "time_stat_get": {
        "desc": "Get time tracking entry by ID",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Time stat ID"},
        },
    },
    "time_stat_create": {
        "desc": "Create time tracking entry",
        "params": {
            "start": {"type": "str", "required": True, "desc": "Start datetime ISO"},
            "secondsPassed": {"type": "int", "required": True, "desc": "Seconds passed"},
            "relatedTaskId": {"type": "str", "desc": "Related task ID"},
            "source": {"type": "int", "desc": "0=pomodoro, 1=stopwatch"},
        },
    },
    "time_stat_update": {
        "desc": "Update time tracking entry",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Time stat ID"},
            "start": {"type": "str", "desc": "Start datetime ISO"},
            "secondsPassed": {"type": "int", "desc": "Seconds passed"},
            "relatedTaskId": {"type": "str", "desc": "Related task ID"},
            "source": {"type": "int", "desc": "0=pomodoro, 1=stopwatch"},
        },
    },
    "time_stat_delete": {
        "desc": "Delete time tracking entry",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Time stat ID"},
        },
    },
    "time_stat_bulk_delete": {
        "desc": "Bulk delete time tracking entries by filter",
        "params": {
            "date_from": {"type": "str", "desc": "Date from ISO"},
            "date_to": {"type": "str", "desc": "Date to ISO"},
            "related_task_id": {"type": "str", "desc": "Filter by task ID"},
        },
    },

    # --- References ---
    "rebuild_references": {
        "desc": "Regenerate references cache (projects.json, tags.json) from API and merge descriptions from meta files",
        "params": {},
    },
    "generate_meta_template": {
        "desc": "Generate meta template file with _title fields for easy editing",
        "params": {
            "type": {
                "type": "str",
                "required": True,
                "desc": "Type: 'projects' or 'tags'"
            },
            "overwrite": {
                "type": "bool",
                "desc": "Overwrite existing file (default: false)"
            }
        }
    },
    "find_project": {
        "desc": "Find project by name with auto-rebuild on cache miss",
        "params": {
            "name": {
                "type": "str",
                "required": True,
                "desc": "Project name or partial name (case-insensitive search)"
            },
            "exact": {
                "type": "bool",
                "desc": "Exact match only (default: false, allows partial match)"
            }
        }
    },
    "find_tag": {
        "desc": "Find tag by name with auto-rebuild on cache miss",
        "params": {
            "name": {
                "type": "str",
                "required": True,
                "desc": "Tag name or partial name (case-insensitive search)"
            },
            "exact": {
                "type": "bool",
                "desc": "Exact match only (default: false, allows partial match)"
            }
        }
    },

    # --- Batch Tools ---
    "task_full": {
        "desc": "Get task with its note (batch: task_get + note_list). Accepts task ID or Singularity URL.",
        "params": {
            "task_id": {
                "type": "str",
                "desc": "Task ID (T-xxx) or Singularity URL (singularityapp://... or https://web.singularity-app.com/...)"
            }
        }
    },
    "project_tasks_full": {
        "desc": "Get all tasks of a project with their notes (batch: task_list + note_list for all tasks)",
        "params": {
            "project_id": {
                "type": "str",
                "required": True,
                "desc": "Project ID (P-xxx)"
            },
            "include_notes": {
                "type": "bool",
                "desc": "Include task notes (default: true)"
            }
        }
    },

    # --- Inbox Tools ---
    "inbox_list": {
        "desc": "Get all tasks in Inbox (tasks without projectId). Returns up to 1000 tasks.",
        "params": {
            "include_notes": {
                "type": "bool",
                "desc": "Include task notes (default: false)"
            }
        }
    },
    "inbox_suggest": {
        "desc": "Suggest project assignments for Inbox tasks based on title/note analysis using cached projects and tags",
        "params": {
            "task_ids": {
                "type": "list",
                "desc": "List of task IDs to analyze (optional, if not provided analyzes all inbox tasks)"
            },
            "min_confidence": {
                "type": "float",
                "desc": "Minimum confidence score 0.0-1.0 (default: 0.3)"
            }
        }
    },
}


# ---------------------------------------------------------------------------
# Dispatch table: tool_name -> (resource_key, handler_fn)
# ---------------------------------------------------------------------------

TOOL_DISPATCH = {}

# Auto-generate standard CRUD for every resource
_ACTION_MAP = {
    "list": _list_handler,
    "get": _get_handler,
    "create": _create_handler,
    "update": _update_handler,
    "delete": _delete_handler,
}

for _res_key in RESOURCES:
    for _action, _handler in _ACTION_MAP.items():
        _tool_name = f"{_res_key}_{_action}"
        if _tool_name in TOOL_CATALOG:
            TOOL_DISPATCH[_tool_name] = (_res_key, _handler)

# Special: time_stat_bulk_delete
TOOL_DISPATCH["time_stat_bulk_delete"] = (
    "time_stat", _time_stat_bulk_delete_handler
)



# ---------------------------------------------------------------------------
# Write tools set (blocked in read_only mode)
# ---------------------------------------------------------------------------

WRITE_TOOLS = set()
for _name in TOOL_CATALOG:
    for _suffix in ("_create", "_update", "_delete", "_bulk_delete"):
        if _name.endswith(_suffix):
            WRITE_TOOLS.add(_name)


# ---------------------------------------------------------------------------
# References Cache (rebuild_references tool)
# ---------------------------------------------------------------------------

def _load_indexed_projects():
    """Load projects.json and build search indexes.

    Returns dict with:
      - 'raw': list of all projects
      - 'by_id': {project_id: project}
      - 'by_title_lower': {title.lower(): project}
      - 'by_parent': {parent_id: [child_projects]}

    Returns None if file doesn't exist.
    """
    projects_file = REFS_DIR / "projects.json"
    if not projects_file.exists():
        return None

    with projects_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    projects = data.get("projects", [])

    # Build indexes
    by_id = {}
    by_title_lower = {}
    by_parent = {}

    for p in projects:
        pid = p["id"]
        title_lower = p.get("title", "").lower()
        parent = p.get("parent")

        by_id[pid] = p
        by_title_lower[title_lower] = p

        if parent:
            if parent not in by_parent:
                by_parent[parent] = []
            by_parent[parent].append(p)

    return {
        "raw": projects,
        "by_id": by_id,
        "by_title_lower": by_title_lower,
        "by_parent": by_parent,
        "metadata": {
            "generated": data.get("generated"),
            "total": data.get("total", len(projects)),
            "archived": data.get("archived", 0),
        }
    }


def _load_indexed_tags():
    """Load tags.json and build search indexes.

    Returns dict with:
      - 'raw': list of all tags
      - 'by_id': {tag_id: tag}
      - 'by_title_lower': {title.lower(): tag}
      - 'by_parent': {parent_id: [child_tags]}

    Returns None if file doesn't exist.
    """
    tags_file = REFS_DIR / "tags.json"
    if not tags_file.exists():
        return None

    with tags_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    tags = data.get("tags", [])

    # Build indexes
    by_id = {}
    by_title_lower = {}
    by_parent = {}

    for t in tags:
        tid = t["id"]
        title_lower = t.get("title", "").lower()
        parent = t.get("parent")

        by_id[tid] = t
        by_title_lower[title_lower] = t

        if parent:
            if parent not in by_parent:
                by_parent[parent] = []
            by_parent[parent].append(t)

    return {
        "raw": tags,
        "by_id": by_id,
        "by_title_lower": by_title_lower,
        "by_parent": by_parent,
        "metadata": {
            "generated": data.get("generated"),
            "total": data.get("total", len(tags)),
        }
    }


def _rebuild_references_handler(client: SingularityClient, _res_key: str,
                                _args: dict) -> dict:
    """Fetch projects and tags from API, merge meta descriptions, write JSON caches."""
    REFS_DIR.mkdir(exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --- Fetch all projects ---
    proj_data = client.get("/v2/project", params={
        "maxCount": 1000, "includeRemoved": "false",
    })
    projects_raw = (
        proj_data if isinstance(proj_data, list)
        else proj_data.get("projects", proj_data.get("items", []))
    )
    # Filter out removed just in case
    projects_raw = [p for p in projects_raw if not p.get("removed")]

    # --- Fetch all tags ---
    tag_data = client.get("/v2/tag", params={
        "maxCount": 1000, "includeRemoved": "false",
    })
    tags_raw = (
        tag_data if isinstance(tag_data, list)
        else tag_data.get("tags", tag_data.get("items", []))
    )
    tags_raw = [t for t in tags_raw if not t.get("removed")]

    # --- Load meta files ---
    project_meta_path = REFS_DIR / "project_meta.json"
    project_meta: dict = {}
    if project_meta_path.exists():
        try:
            project_meta = json.loads(
                project_meta_path.read_text(encoding="utf-8")
            )
        except Exception:
            pass

    tag_meta_path = REFS_DIR / "tag_meta.json"
    tag_meta: dict = {}
    if tag_meta_path.exists():
        try:
            tag_meta = json.loads(
                tag_meta_path.read_text(encoding="utf-8")
            )
        except Exception:
            pass

    # --- Build projects.json ---
    projects_out = []
    proj_desc_merged = 0
    for p in projects_raw:
        pid = p["id"]
        meta_entry = project_meta.get(pid, {})
        # Only take description, ignore _ prefixed fields
        desc = meta_entry.get("description")
        if desc:
            proj_desc_merged += 1
        projects_out.append({
            "id": pid,
            "title": p.get("title", ""),
            "emoji": p.get("emoji"),
            "color": p.get("color"),
            "parent": p.get("parent"),
            "isNotebook": p.get("isNotebook", False),
            "archived": p.get("archive", False),
            "description": desc,
        })

    # Sort: non-archived first, then alphabetical by title
    projects_out.sort(
        key=lambda x: (x["archived"], (x["title"] or "").lower())
    )

    archived_count = sum(1 for p in projects_out if p["archived"])
    projects_data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total": len(projects_out),
        "archived": archived_count,
        "with_description": proj_desc_merged,
        "projects": projects_out,
    }
    (REFS_DIR / "projects.json").write_text(
        json.dumps(projects_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- Build tags.json ---
    tags_out = []
    tag_desc_merged = 0
    for t in tags_raw:
        tid = t["id"]
        meta_entry = tag_meta.get(tid, {})
        # Only take description, ignore _ prefixed fields
        desc = meta_entry.get("description")
        if desc:
            tag_desc_merged += 1
        tags_out.append({
            "id": tid,
            "title": t.get("title", ""),
            "color": t.get("color"),
            "hotkey": t.get("hotkey"),
            "parent": t.get("parent"),
            "description": desc,
        })

    tags_out.sort(key=lambda x: (x["title"] or "").lower())

    tags_data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total": len(tags_out),
        "with_description": tag_desc_merged,
        "tags": tags_out,
    }
    (REFS_DIR / "tags.json").write_text(
        json.dumps(tags_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- Build task_groups.json (project_id -> base_task_group_id mapping) ---
    print(f"[singularity] Fetching task groups for {len(projects_out)} projects...", file=sys.stderr)

    task_groups_mapping = {}
    errors_count = 0

    for idx, p in enumerate(projects_out, 1):
        project_id = p["id"]

        # Progress indicator every 10 projects
        if idx % 10 == 0 or idx == len(projects_out):
            print(f"[singularity] Progress: {idx}/{len(projects_out)} projects", file=sys.stderr)

        try:
            # Get task groups for this project
            tg_data = client.get("/v2/task-group", params={
                "parent": project_id,
                "maxCount": 100,
                "includeRemoved": "false",
            })

            task_groups = tg_data.get("taskGroups", [])

            if task_groups:
                # Find base task group (usually first one, or one without parent in task group hierarchy)
                base_tg = task_groups[0]  # First task group is typically the base
                task_groups_mapping[project_id] = base_tg["id"]
        except Exception as e:
            # Don't fail entire rebuild if one project fails
            errors_count += 1
            print(f"[singularity] Warning: Failed to fetch task groups for {project_id}: {e}", file=sys.stderr)
            continue

    task_groups_data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total_projects": len(projects_out),
        "mapped": len(task_groups_mapping),
        "errors": errors_count,
        "mappings": task_groups_mapping,
    }

    (REFS_DIR / "task_groups.json").write_text(
        json.dumps(task_groups_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[singularity] Task groups cache built: {len(task_groups_mapping)} mappings", file=sys.stderr)

    return {
        "status": "ok",
        "generated": today,
        "projects": f"{len(projects_out)} projects ({archived_count} archived, {proj_desc_merged} with description)",
        "tags": f"{len(tags_out)} tags ({tag_desc_merged} with description)",
        "task_groups": f"{len(task_groups_mapping)} project→task_group mappings ({errors_count} errors)",
        "files": [
            "references/projects.json",
            "references/tags.json",
            "references/task_groups.json",
        ],
    }


def _generate_meta_template_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    """Generate meta template file with _title for user-friendly editing."""
    meta_type = args.get("type")
    if meta_type not in ("projects", "tags"):
        raise ValueError("type must be 'projects' or 'tags'")

    overwrite = args.get("overwrite", False)

    # Paths
    cache_file = REFS_DIR / f"{meta_type}.json"
    meta_file = REFS_DIR / f"{meta_type[:-1]}_meta.json"  # project_meta.json or tag_meta.json

    # Check if cache exists
    if not cache_file.exists():
        raise FileNotFoundError(
            f"{cache_file} not found. Run rebuild_references first."
        )

    # Check if meta file exists
    if meta_file.exists() and not overwrite:
        raise FileExistsError(
            f"{meta_file} already exists. Use overwrite=true to replace."
        )

    # Load cache
    with cache_file.open("r", encoding="utf-8") as f:
        cache_data = json.load(f)

    items = cache_data.get(meta_type, [])

    # Load existing meta (if exists) to preserve descriptions
    existing_meta = {}
    if meta_file.exists():
        try:
            with meta_file.open("r", encoding="utf-8") as f:
                existing_meta = json.load(f)
        except Exception:
            pass

    # Build template
    template = {}
    for item in items:
        item_id = item["id"]
        existing = existing_meta.get(item_id, {})

        template[item_id] = {
            "_title": item.get("title", ""),
            "description": existing.get("description", "")
        }

    # Write template
    REFS_DIR.mkdir(exist_ok=True)
    with meta_file.open("w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)

    return {
        "status": "success",
        "file": str(meta_file),
        "items": len(template),
        "overwritten": meta_file.exists() and overwrite
    }


def _find_project_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    """Find project by name using indexed search. Rebuild cache on miss and retry.

    Returns projects with task_group_id field added from task_groups.json cache.
    """
    name = args.get("name", "").lower()
    exact = args.get("exact", False)

    if not name:
        raise ValueError("name is required")

    def search_project():
        """Search in indexed cache and enrich with task_group_id."""
        indexed = _load_indexed_projects()
        if not indexed:
            return None

        # Load task_groups mapping
        task_groups_file = REFS_DIR / "task_groups.json"
        task_groups_mapping = {}
        if task_groups_file.exists():
            try:
                with task_groups_file.open("r", encoding="utf-8") as f:
                    tg_data = json.load(f)
                task_groups_mapping = tg_data.get("mappings", {})
            except Exception:
                pass

        matches = []

        if exact:
            # O(1) exact match using index
            match = indexed["by_title_lower"].get(name)
            if match:
                # Enrich with task_group_id
                project_id = match["id"]
                match_copy = match.copy()
                match_copy["task_group_id"] = task_groups_mapping.get(project_id)
                matches.append(match_copy)
        else:
            # Partial match - still need to iterate, but more efficient
            for p in indexed["raw"]:
                title_lower = p.get("title", "").lower()
                if name in title_lower:
                    # Enrich with task_group_id
                    project_id = p["id"]
                    p_copy = p.copy()
                    p_copy["task_group_id"] = task_groups_mapping.get(project_id)
                    matches.append(p_copy)

        return matches

    # First attempt
    matches = search_project()

    if matches:
        return {
            "found": True,
            "count": len(matches),
            "projects": matches
        }

    # Cache miss → rebuild
    print(f"[singularity] Project '{name}' not found in cache, rebuilding...", file=sys.stderr)
    _rebuild_references_handler(client, None, {})

    # Second attempt
    matches = search_project()

    if matches:
        return {
            "found": True,
            "count": len(matches),
            "projects": matches,
            "cache_rebuilt": True
        }

    return {
        "found": False,
        "count": 0,
        "projects": [],
        "cache_rebuilt": True,
        "message": f"Project '{name}' not found even after cache rebuild"
    }


def _find_tag_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    """Find tag by name using indexed search. Rebuild cache on miss and retry."""
    name = args.get("name", "").lower()
    exact = args.get("exact", False)

    if not name:
        raise ValueError("name is required")

    def search_tag():
        """Search in indexed cache."""
        indexed = _load_indexed_tags()
        if not indexed:
            return None

        matches = []

        if exact:
            # O(1) exact match using index
            match = indexed["by_title_lower"].get(name)
            if match:
                matches.append(match)
        else:
            # Partial match - still need to iterate, but more efficient
            for t in indexed["raw"]:
                title_lower = t.get("title", "").lower()
                if name in title_lower:
                    matches.append(t)

        return matches

    # First attempt
    matches = search_tag()

    if matches:
        return {
            "found": True,
            "count": len(matches),
            "tags": matches
        }

    # Cache miss → rebuild
    print(f"[singularity] Tag '{name}' not found in cache, rebuilding...", file=sys.stderr)
    _rebuild_references_handler(client, None, {})

    # Second attempt
    matches = search_tag()

    if matches:
        return {
            "found": True,
            "count": len(matches),
            "tags": matches,
            "cache_rebuilt": True
        }

    return {
        "found": False,
        "count": 0,
        "tags": [],
        "cache_rebuilt": True,
        "message": f"Tag '{name}' not found even after cache rebuild"
    }


# Register rebuild_references in dispatch (after function definition)
def _task_full_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    """Get task with its note (batch: task_get + note_list).

    Accepts task ID (T-xxx) or Singularity URL:
    - singularityapp://?&page=any&id=T-...
    - https://web.singularity-app.com/#/?&id=T-...
    """
    import re
    from urllib.parse import urlparse, parse_qs

    task_id_input = args.get("task_id", "").strip()

    # Parse URL if needed
    task_id = task_id_input
    if "://" in task_id_input:
        # URL format: extract id parameter
        parsed = urlparse(task_id_input)

        if parsed.scheme == "singularityapp":
            # singularityapp://?&page=any&id=T-xxx
            qs = parse_qs(parsed.query)
            if "id" in qs:
                task_id = qs["id"][0]
        elif "singularity-app.com" in parsed.netloc:
            # https://web.singularity-app.com/#/?&id=T-xxx
            # Fragment contains query string
            fragment = parsed.fragment
            if "?" in fragment:
                qs_part = fragment.split("?", 1)[1]
                qs = parse_qs(qs_part)
                if "id" in qs:
                    task_id = qs["id"][0]

        # Extract T-UUID from id (may have timestamp suffix like -20260222)
        match = re.search(r'(T-[0-9a-f-]+)', task_id)
        if match:
            task_id = match.group(1)

    if not task_id.startswith("T-"):
        return {"error": f"Invalid task ID: {task_id_input}"}

    # Get task
    task = client.get(f"/v2/task/{task_id}")

    # Get note if exists
    note = None
    note_list = client.get("/v2/note", params={"containerId": task_id, "maxCount": 1})
    notes = note_list.get("content", [])
    if notes:
        note = notes[0]

    return {
        "task": task,
        "note": note
    }


def _project_tasks_full_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    """Get all tasks of a project with their notes (batch: task_list + note_list for all tasks)."""
    project_id = args.get("project_id", "").strip()
    include_notes = args.get("include_notes", True)

    if not project_id.startswith("P-"):
        return {"error": f"Invalid project ID: {project_id}"}

    # Get all tasks (API doesn't support project_id filter)
    # Use task_list tool internally for consistency
    from copy import copy
    task_list_args = {"max_count": 1000}

    # Call task_list to get all tasks
    dispatch_info = TOOL_DISPATCH.get("task_list")
    if dispatch_info:
        res_key, handler = dispatch_info
        tasks_response = handler(client, res_key, task_list_args)
        all_tasks = tasks_response.get("tasks", [])
    else:
        # Fallback to direct API call
        tasks_response = client.get("/v2/task", params={"maxCount": 1000})
        all_tasks = tasks_response.get("content", tasks_response.get("tasks", []))

    # Filter tasks by project_id on client side
    tasks = [t for t in all_tasks if t.get("projectId") == project_id]

    if not include_notes:
        return {
            "project_id": project_id,
            "total_tasks": len(tasks),
            "tasks": tasks
        }

    # Get notes for all tasks
    tasks_with_notes = []
    for task in tasks:
        task_id = task["id"]

        # Get note for this task
        note = None
        if include_notes:
            note_list = client.get("/v2/note", params={"containerId": task_id, "maxCount": 1})
            notes = note_list.get("content", [])
            if notes:
                note = notes[0]

        tasks_with_notes.append({
            "task": task,
            "note": note
        })

    return {
        "project_id": project_id,
        "total_tasks": len(tasks_with_notes),
        "tasks_with_notes": tasks_with_notes
    }


def _inbox_list_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    """Get all tasks in Inbox (tasks without projectId).

    Uses maxCount=1000 to get all inbox tasks in one request.
    """
    include_notes = args.get("include_notes", False)

    # Get all tasks with max limit
    tasks_response = client.get("/v2/task", params={"maxCount": 1000})
    all_tasks = tasks_response.get("content", tasks_response.get("tasks", []))

    # Filter tasks without projectId (Inbox tasks)
    inbox_tasks = [t for t in all_tasks if not t.get("projectId")]

    if not include_notes:
        return {
            "total": len(inbox_tasks),
            "tasks": inbox_tasks
        }

    # Get notes for all inbox tasks
    tasks_with_notes = []
    for task in inbox_tasks:
        task_id = task["id"]

        # Get note for this task
        note = None
        note_list = client.get("/v2/note", params={"containerId": task_id, "maxCount": 1})
        notes = note_list.get("content", [])
        if notes:
            note = notes[0]

        tasks_with_notes.append({
            "task": task,
            "note": note
        })

    return {
        "total": len(tasks_with_notes),
        "tasks_with_notes": tasks_with_notes
    }


def _inbox_suggest_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    """Suggest project/tag assignments for Inbox tasks using cached metadata.

    Analyzes task title and note content, matches against project/tag titles and descriptions.
    Returns suggestions sorted by confidence score.
    """
    task_ids = args.get("task_ids")
    min_confidence = args.get("min_confidence", 0.3)

    # Load cached projects and tags
    indexed_projects = _load_indexed_projects()
    indexed_tags = _load_indexed_tags()

    if not indexed_projects or not indexed_tags:
        return {
            "error": "Cache not available. Run rebuild_references first."
        }

    projects = indexed_projects["raw"]
    tags = indexed_tags["raw"]

    # Load task groups mapping for project suggestions
    task_groups_file = REFS_DIR / "task_groups.json"
    task_groups_mapping = {}
    if task_groups_file.exists():
        try:
            with task_groups_file.open("r", encoding="utf-8") as f:
                tg_data = json.load(f)
            task_groups_mapping = tg_data.get("mappings", {})
        except Exception:
            pass

    # Get inbox tasks to analyze
    if task_ids:
        # Get specific tasks
        tasks_to_analyze = []
        for task_id in task_ids:
            try:
                task = client.get(f"/v2/task/{task_id}")
                tasks_to_analyze.append(task)
            except Exception:
                pass
    else:
        # Get all inbox tasks
        inbox_response = _inbox_list_handler(client, res_key, {"include_notes": False})
        tasks_to_analyze = inbox_response.get("tasks", [])

    suggestions = []

    for task in tasks_to_analyze:
        task_id = task.get("id")
        task_title = task.get("title", "").lower()
        task_note = task.get("note", "").lower()
        combined_text = f"{task_title} {task_note}"

        # Score projects
        project_scores = []
        for proj in projects:
            score = 0.0
            proj_title = proj.get("title", "").lower()
            proj_desc = proj.get("description", "").lower() if proj.get("description") else ""

            # Title match
            if proj_title in combined_text:
                score += 0.6
            elif any(word in combined_text for word in proj_title.split() if len(word) > 3):
                score += 0.3

            # Description match
            if proj_desc and any(word in combined_text for word in proj_desc.split() if len(word) > 4):
                score += 0.2

            if score >= min_confidence:
                project_scores.append({
                    "project_id": proj["id"],
                    "project_title": proj["title"],
                    "project_emoji": proj.get("emoji"),
                    "task_group_id": task_groups_mapping.get(proj["id"]),
                    "confidence": round(score, 2)
                })

        # Score tags
        tag_scores = []
        for tag in tags:
            score = 0.0
            tag_title = tag.get("title", "").lower()
            tag_desc = tag.get("description", "").lower() if tag.get("description") else ""

            # Title match
            if tag_title in combined_text:
                score += 0.7
            elif any(word in combined_text for word in tag_title.split() if len(word) > 3):
                score += 0.4

            # Description match
            if tag_desc and any(word in combined_text for word in tag_desc.split() if len(word) > 4):
                score += 0.2

            if score >= min_confidence:
                tag_scores.append({
                    "tag_id": tag["id"],
                    "tag_title": tag["title"],
                    "tag_color": tag.get("color"),
                    "confidence": round(score, 2)
                })

        # Sort by confidence
        project_scores.sort(key=lambda x: x["confidence"], reverse=True)
        tag_scores.sort(key=lambda x: x["confidence"], reverse=True)

        suggestions.append({
            "task_id": task_id,
            "task_title": task.get("title"),
            "suggested_projects": project_scores[:5],  # Top 5
            "suggested_tags": tag_scores[:5],  # Top 5
            "has_suggestions": len(project_scores) > 0 or len(tag_scores) > 0
        })

    return {
        "total_tasks": len(suggestions),
        "suggestions": suggestions,
        "min_confidence": min_confidence
    }


TOOL_DISPATCH["rebuild_references"] = (
    "project", _rebuild_references_handler
)
TOOL_DISPATCH["generate_meta_template"] = (None, _generate_meta_template_handler)
TOOL_DISPATCH["find_project"] = (None, _find_project_handler)
TOOL_DISPATCH["find_tag"] = (None, _find_tag_handler)
TOOL_DISPATCH["task_full"] = (None, _task_full_handler)
TOOL_DISPATCH["project_tasks_full"] = (None, _project_tasks_full_handler)
TOOL_DISPATCH["inbox_list"] = (None, _inbox_list_handler)
TOOL_DISPATCH["inbox_suggest"] = (None, _inbox_suggest_handler)


def _check_and_refresh_cache(cfg: dict) -> None:
    """Auto-refresh references cache if missing or expired.

    Refreshes if:
    - Cache files missing
    - Cache older than cache_ttl_days (from config)
    """
    cache_ttl_days = cfg.get("cache_ttl_days", 30)  # Default: 30 days

    projects_file = REFS_DIR / "projects.json"
    tags_file = REFS_DIR / "tags.json"
    task_groups_file = REFS_DIR / "task_groups.json"

    # If any cache missing → rebuild all
    if not projects_file.exists() or not tags_file.exists() or not task_groups_file.exists():
        print("[singularity] Cache missing, rebuilding...", file=sys.stderr)
        _rebuild_references_handler(SingularityClient(cfg["base_url"], cfg["token"]), None, {})
        return

    # Check age
    try:
        with projects_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        generated_str = data.get("generated")
        if not generated_str:
            # Old format without timestamp → rebuild
            print("[singularity] Cache has no timestamp, rebuilding...", file=sys.stderr)
            _rebuild_references_handler(SingularityClient(cfg["base_url"], cfg["token"]), None, {})
            return

        generated = datetime.fromisoformat(generated_str)
        # Make aware if naive
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)

        age_days = (datetime.now(timezone.utc) - generated).days

        if age_days >= cache_ttl_days:
            print(f"[singularity] Cache expired ({age_days} days old, TTL={cache_ttl_days}), rebuilding...", file=sys.stderr)
            _rebuild_references_handler(SingularityClient(cfg["base_url"], cfg["token"]), None, {})

    except Exception as e:
        print(f"[singularity] Error checking cache age: {e}, rebuilding...", file=sys.stderr)
        _rebuild_references_handler(SingularityClient(cfg["base_url"], cfg["token"]), None, {})


# ---------------------------------------------------------------------------
# Project Cache Management
# ---------------------------------------------------------------------------

CACHE_MAX_AGE_DAYS = 7
CACHE_FILE = ROOT / "projects_cache.md"


def _refresh_project_cache(cfg: dict = None) -> None:
    """Fetch all projects and write projects_cache.md + update config.json."""
    if cfg is None:
        cfg = load_config()

    print("[singularity] Refreshing project cache...", file=sys.stderr)

    client = SingularityClient(cfg["base_url"], cfg["token"])

    # Fetch all projects (skip removed)
    data = client.get("/v2/project", params={"maxCount": 1000})
    projects = data if isinstance(data, list) else data.get("projects", data.get("items", []))

    # Filter removed
    projects = [p for p in projects if not p.get("removed")]

    # Build id -> project map and parent -> children map
    by_id = {p["id"]: p for p in projects}
    children: dict = {}  # parent_id -> [project, ...]
    roots = []

    for p in projects:
        parent = p.get("parent")
        if parent and parent in by_id:
            children.setdefault(parent, []).append(p)
        else:
            roots.append(p)

    # Sort alphabetically by title at each level
    roots.sort(key=lambda p: (p.get("title") or "").lower())
    for lst in children.values():
        lst.sort(key=lambda p: (p.get("title") or "").lower())

    # Build flat indented lines recursively
    lines = []

    def _walk(project, depth: int) -> None:
        indent = "  " * depth
        title = project.get("title") or "(no title)"
        pid = project["id"]
        lines.append(f"{indent}- {title}  [{pid}]")
        for child in children.get(project["id"], []):
            _walk(child, depth + 1)

    for root in roots:
        _walk(root, 0)

    # Write cache file (utf-8, no BOM)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    content = (
        "# Singularity Projects Cache\n"
        f"<!-- cache_updated: {now_iso} -->\n"
        "\n"
        + "\n".join(lines)
        + "\n"
    )
    CACHE_FILE.write_text(content, encoding="utf-8")

    # Update config.json with cache_updated timestamp
    cfg_path = ROOT / "config.json"
    cfg["cache_updated"] = now_iso
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    count = len(projects)
    print(f"[singularity] Cache updated ({count} projects)", file=sys.stderr)


def _maybe_auto_refresh_cache(cfg: dict) -> None:
    """Auto-refresh cache if missing or older than CACHE_MAX_AGE_DAYS."""
    if not CACHE_FILE.exists():
        _refresh_project_cache(cfg)
        return

    cache_updated_str = cfg.get("cache_updated")
    if not cache_updated_str:
        _refresh_project_cache(cfg)
        return

    try:
        cache_updated = datetime.fromisoformat(cache_updated_str)
        # Make aware if naive
        if cache_updated.tzinfo is None:
            cache_updated = cache_updated.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - cache_updated).days
        if age_days >= CACHE_MAX_AGE_DAYS:
            _refresh_project_cache(cfg)
    except (ValueError, TypeError):
        _refresh_project_cache(cfg)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Singularity App Skill CLI -- REST API client for task "
                    "management, projects, habits, kanban, notes, time tracking"
    )
    parser.add_argument(
        "--call",
        help='JSON tool call: {"tool":"...","arguments":{...}}',
    )
    parser.add_argument("--describe", help="Show tool schema by name")
    parser.add_argument(
        "--list", action="store_true", help="List all available tools"
    )
    parser.add_argument(
        "--refresh-cache", action="store_true",
        help="Refresh projects_cache.md from API and update config.json cache_updated",
    )

    cli_args = parser.parse_args()

    # -- --refresh-cache ----------------------------------------------------
    if cli_args.refresh_cache:
        try:
            _refresh_project_cache()
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # -- --list -------------------------------------------------------------
    if cli_args.list:
        tools = [
            {"name": name, "description": meta["desc"]}
            for name, meta in TOOL_CATALOG.items()
        ]
        print(json.dumps(tools, indent=2, ensure_ascii=False))
        return

    # -- --describe ---------------------------------------------------------
    if cli_args.describe:
        name = cli_args.describe
        if name not in TOOL_CATALOG:
            print(f"Tool not found: {name}", file=sys.stderr)
            sys.exit(1)
        meta = TOOL_CATALOG[name]
        schema = {
            "name": name,
            "description": meta["desc"],
            "inputSchema": {
                "type": "object",
                "properties": {
                    k: {
                        "type": v["type"],
                        "description": v.get("desc", ""),
                        **({"default": v["default"]}
                           if "default" in v else {}),
                    }
                    for k, v in meta["params"].items()
                },
                "required": [
                    k for k, v in meta["params"].items()
                    if v.get("required")
                ],
            },
        }
        print(json.dumps(schema, indent=2, ensure_ascii=False))
        return

    # -- --call -------------------------------------------------------------
    if cli_args.call:
        try:
            call_data = json.loads(cli_args.call)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)

        tool_name = call_data.get("tool")
        arguments = call_data.get("arguments", {})

        if not tool_name:
            print('Missing "tool" key in call JSON', file=sys.stderr)
            sys.exit(1)

        if tool_name not in TOOL_DISPATCH:
            print(f"Unknown tool: {tool_name}", file=sys.stderr)
            print("Use --list to see available tools", file=sys.stderr)
            sys.exit(1)

        try:
            cfg = load_config()

            # Auto-refresh cache if missing or stale (silent, stderr only)
            try:
                _maybe_auto_refresh_cache(cfg)
                # Reload config in case cache_updated was written
                cfg = load_config()
            except Exception:
                pass  # Never block tool execution due to cache errors

            # Auto-refresh references cache if needed
            try:
                _check_and_refresh_cache(cfg)
                cfg = load_config()  # Reload in case updated
            except Exception:
                pass  # Never block tool execution

            if cfg.get("read_only") and tool_name in WRITE_TOOLS:
                print(
                    f"Error: tool '{tool_name}' is a write operation, "
                    f"but config.json has read_only=true",
                    file=sys.stderr,
                )
                sys.exit(1)

            client = SingularityClient(
                cfg["base_url"], cfg["token"]
            )

            res_key, handler = TOOL_DISPATCH[tool_name]
            result = handler(client, res_key, arguments)
            print(json.dumps(result, indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # -- no args ------------------------------------------------------------
    parser.print_help()


if __name__ == "__main__":
    main()
