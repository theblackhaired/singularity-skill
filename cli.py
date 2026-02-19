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
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent

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

    cli_args = parser.parse_args()

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
