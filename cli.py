#!/usr/bin/env python3
"""Singularity App Skill CLI -- direct REST API client for task management.

Usage:
  python cli.py --list
  python cli.py --describe project_list
  python cli.py --call '{"tool":"project_list","arguments":{}}'

Python 3.10+ stdlib only (urllib, json, ssl) — PEP 604 union syntax used.
Test/dev dependencies in requirements-dev.txt (jsonschema). Bearer token auth.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
REFS_DIR = ROOT / "references"

# Skill version — bumped per references/contract/decisions.md §Versioning.
# 1.0.0  Iter 0 baseline
# 1.1.0  Iter 1: derived tools return additive {status,partial,note_status,warnings}
# 1.2.0  Iter 2+3: paginator (no more silent maxCount=1000 truncation),
#                  atomic cache writes with CacheMeta, secrets-safe auto-refresh
# 1.3.0  Iter 4 (T4.3): --describe emits valid JSON Schema draft-07
#                       (closes Drift 4: int→integer, str→string, items/properties)
#                       + Iter 7: token redaction in error bodies (security)
# 1.4.0  Iter 4 (T4.4-T4.9): tools.json regen + --verify-metadata + schema tests
#                            + tools.json now includes derived tools (closes Drift 3)
# 1.4.2  Cache correctness: incomplete rebuilds and degraded read responses.
# 1.5.0  JSON-only project descriptions, project_describe, migration state.
SKILL_VERSION = "1.5.0"

# Iteration 1: notes resolved per Decision A in notes-decision.md.
from note_resolver import resolve_note  # noqa: E402  -- after sys.stdout reconfigure
# Iteration 6 / T6.9: --doctor logic extracted to dedicated module.
from doctor import doctor_run as _doctor_run_impl  # noqa: E402
# HTTP client extracted to dedicated module.
from client import SingularityClient  # noqa: E402
from errors import StructuredError, _error_response  # noqa: E402
# Iteration 2: shared pagination helper (T2.1). Kept in cli namespace for tests.
from pagination import iterate_pages   # noqa: E402
# Cache primitives and Stage 2 cache handlers.
from cache import (                     # noqa: E402
    read_cache,
    _sha256_file,
    _projects_path,
    _count_project_descriptions,
    _ensure_description_migration_meta,
    _load_projects_data,
    _write_projects_data,
    _complete_description_migration_if_pending,
    _check_description_migration,
    _rebuild_references_handler,
    _check_and_refresh_cache,
)

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

from resources import RESOURCES  # noqa: E402
from crud import (  # noqa: E402
    _list_handler,
    _get_handler,
    _create_handler,
    _update_handler,
    _delete_handler,
    _time_stat_bulk_delete_handler,
)
import derived as _derived  # noqa: E402


def _sync_derived_module() -> None:
    _derived.REFS_DIR = REFS_DIR
    if "_rebuild_references_handler" in globals():
        _derived._rebuild_references_handler = _rebuild_references_handler


def _load_indexed_projects():
    _sync_derived_module()
    return _derived._load_indexed_projects()


def _load_indexed_tags():
    _sync_derived_module()
    return _derived._load_indexed_tags()


def _generate_meta_template_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    _sync_derived_module()
    return _derived._generate_meta_template_handler(client, res_key, args)


def _find_project_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    _sync_derived_module()
    return _derived._find_project_handler(client, res_key, args)


def _find_tag_handler(client: SingularityClient, res_key: str, args: dict) -> dict:
    _sync_derived_module()
    return _derived._find_tag_handler(client, res_key, args)


def _task_full_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    _sync_derived_module()
    return _derived._task_full_handler(client, res_key, args)


def _project_tasks_full_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    _sync_derived_module()
    return _derived._project_tasks_full_handler(client, res_key, args)


def _inbox_list_handler(client: "SingularityClient", res_key: str, args: dict) -> dict:
    _sync_derived_module()
    return _derived._inbox_list_handler(client, res_key, args)


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
            "tags": {"type": "list", "items": {"type": "string"}, "desc": "Tag IDs array"},
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
            "tags": {"type": "list", "items": {"type": "string"}, "desc": "Tag IDs array"},
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
    "project_describe": {
        "desc": "Edit local project descriptions in references/projects.json",
        "params": {
            "id": {"type": "str", "desc": "Project ID or exact project title for single mode"},
            "text": {"type": "str", "desc": "Description text; null deletes the description"},
            "batch": {
                "type": "object",
                "properties": {},
                "additionalProperties": {"type": ["string", "null"]},
                "desc": "Bulk descriptions keyed by project ID; null deletes",
            },
            "batch_file": {
                "type": "str",
                "desc": "Path to a JSON file containing a batch object",
            },
            "force": {
                "type": "bool",
                "default": False,
                "desc": "Overwrite existing descriptions without DESCRIPTION_EXISTS",
            },
            "dry_run": {
                "type": "bool",
                "default": False,
                "desc": "Preview counts without writing references/projects.json",
            },
            "base_sha256": {
                "type": "str",
                "desc": "Expected sha256 of references/projects.json for CAS",
            },
            "allow_empty": {
                "type": "bool",
                "default": False,
                "desc": "Allow empty string descriptions",
            },
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
            "tags": {"type": "list", "items": {"type": "string"}, "desc": "Tag IDs array"},
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
            "notifies": {"type": "list", "items": {"type": "integer"}, "desc": "Notification minutes array e.g. [60,15]"},
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
            "tags": {"type": "list", "items": {"type": "string"}, "desc": "Tag IDs array"},
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
            "notifies": {"type": "list", "items": {"type": "integer"}, "desc": "Notification minutes array"},
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
            "content": {"type": "list", "items": {"type": "object"}, "required": True, "desc": "Delta array [{insert:...},...] -- last insert must end with newline"},
            "contentType": {"type": "str", "default": "delta", "desc": "Content type (always 'delta')"},
            "externalId": {"type": "str", "desc": "External ID"},
        },
    },
    "note_update": {
        "desc": "Update note",
        "params": {
            "id": {"type": "str", "required": True, "desc": "Note ID"},
            "containerId": {"type": "str", "desc": "Container ID"},
            "content": {"type": "list", "items": {"type": "object"}, "desc": "Delta array"},
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
        "desc": "Regenerate references cache from API while preserving project descriptions in projects.json",
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

LOCAL_WRITE_TOOLS = {"project_describe"}


def _resolve_project_identifier(projects: list, ident: str) -> tuple[str | None, dict | None, list]:
    by_id = {p.get("id"): p for p in projects if p.get("id")}
    if ident in by_id:
        return ident, by_id[ident], []

    matches = [
        p for p in projects
        if (p.get("title") or "").casefold() == str(ident).casefold()
    ]
    if len(matches) == 1:
        return matches[0].get("id"), matches[0], []
    return None, None, matches


def _load_batch_file(path_value: str) -> object:
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise StructuredError(
            "BATCH_INVALID",
            "batch_file is unreadable or invalid JSON",
            batch_file=str(path),
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


def _project_describe_handler(client: SingularityClient, _res_key: str,
                              args: dict) -> dict:
    """Edit local project descriptions in references/projects.json."""
    del client
    args = dict(args or {})
    has_batch = "batch" in args and args.get("batch") is not None
    has_batch_file = bool(args.get("batch_file"))
    dry_run = bool(args.get("dry_run", False))
    force = bool(args.get("force", False))
    allow_empty = bool(args.get("allow_empty", False))
    base_sha256 = args.get("base_sha256")

    if has_batch and has_batch_file:
        return _error_response(
            "BATCH_INVALID",
            "batch and batch_file are mutually exclusive",
        )

    projects_path = _projects_path()
    current_sha = _sha256_file(projects_path) if projects_path.exists() else None
    if base_sha256 and base_sha256 != current_sha:
        return _error_response(
            "CAS_CONFLICT",
            "references/projects.json sha256 does not match base_sha256",
            expected=base_sha256,
            actual=current_sha,
            file=str(projects_path),
        )

    data = _load_projects_data()
    _ensure_description_migration_meta(data)
    projects = data.get("projects", [])
    by_id: dict[str, list[dict]] = {}
    for project in projects:
        pid = project.get("id")
        if pid:
            by_id.setdefault(pid, []).append(project)

    if has_batch_file:
        batch = _load_batch_file(args["batch_file"])
        has_batch = True
    elif has_batch:
        batch = args.get("batch")
    else:
        ident = args.get("id")
        if not ident:
            return _error_response(
                "PROJECT_NOT_FOUND",
                "id is required for single project_describe mode",
                invalid_ids=[ident],
                available_projects=[
                    {"id": p.get("id"), "title": p.get("title", "")}
                    for p in projects
                ],
                available_count=len(projects),
            )
        if "text" not in args:
            return _error_response(
                "INVALID_DESCRIPTION",
                "text is required for single project_describe mode",
                id=ident,
            )
        resolved_id, _project, title_matches = _resolve_project_identifier(projects, str(ident))
        if not resolved_id:
            return _error_response(
                "PROJECT_NOT_FOUND",
                "project was not found by id or unique exact title",
                invalid_ids=[ident],
                candidates=[
                    {"id": p.get("id"), "title": p.get("title", "")}
                    for p in title_matches
                ],
                available_projects=[
                    {"id": p.get("id"), "title": p.get("title", "")}
                    for p in projects
                ],
                available_count=len(projects),
            )
        batch = {resolved_id: args.get("text")}
        has_batch = True

    if not has_batch or not isinstance(batch, dict):
        return _error_response(
            "BATCH_INVALID",
            "project_describe requires a batch object, batch_file, or id+text",
        )

    invalid_ids = [pid for pid in batch if pid not in by_id]
    if invalid_ids:
        return _error_response(
            "BATCH_INVALID",
            "batch contains unknown project IDs",
            invalid_ids=invalid_ids,
            available_projects=[
                {"id": p.get("id"), "title": p.get("title", "")}
                for p in projects
            ],
            available_count=len(projects),
        )

    invalid_descriptions = [
        pid for pid, desc in batch.items()
        if desc is not None and (not isinstance(desc, str) or (desc == "" and not allow_empty))
    ]
    if invalid_descriptions:
        return _error_response(
            "INVALID_DESCRIPTION",
            "description must be a string or null; empty string requires allow_empty=true",
            invalid_ids=invalid_descriptions,
        )

    conflicts = [
        pid for pid, desc in batch.items()
        if (
            desc is not None
            and any(p.get("description") is not None for p in by_id[pid])
            and any(
                p.get("description") != desc
                for p in by_id[pid]
                if p.get("description") is not None
            )
            and not force
        )
    ]
    if conflicts:
        return _error_response(
            "DESCRIPTION_EXISTS",
            "one or more projects already have descriptions; pass force=true to overwrite",
            conflicting_ids=conflicts,
        )

    counts = {
        "added": 0,
        "updated": 0,
        "deleted": 0,
        "skipped": 0,
    }
    for pid, desc in batch.items():
        current = next(
            (p.get("description") for p in by_id[pid] if p.get("description") is not None),
            by_id[pid][0].get("description"),
        )
        if current == desc:
            counts["skipped"] += 1
        elif current is None and desc is not None:
            counts["added"] += 1
        elif current is not None and desc is None:
            counts["deleted"] += 1
        else:
            counts["updated"] += 1

    if dry_run:
        return {
            "status": "ok",
            "dry_run": True,
            "would_add": counts["added"],
            "would_update": counts["updated"],
            "would_delete": counts["deleted"],
            "would_skip": counts["skipped"],
            "with_description_total": _count_project_descriptions(projects),
            "sha256": current_sha,
        }

    for pid, desc in batch.items():
        for project in by_id[pid]:
            project["description"] = desc

    archive_info = _complete_description_migration_if_pending(data)
    _write_projects_data(data)

    result = {
        "status": "ok",
        **counts,
        "with_description_total": data["with_description"],
        "sha256": _sha256_file(projects_path),
    }
    if archive_info:
        result["migration"] = {
            "status": "complete",
            **archive_info,
        }
    return result





TOOL_DISPATCH["rebuild_references"] = (
    "project", _rebuild_references_handler
)
TOOL_DISPATCH["project_describe"] = (None, _project_describe_handler)
TOOL_DISPATCH["generate_meta_template"] = (None, _generate_meta_template_handler)
TOOL_DISPATCH["find_project"] = (None, _find_project_handler)
TOOL_DISPATCH["find_tag"] = (None, _find_tag_handler)
TOOL_DISPATCH["task_full"] = (None, _task_full_handler)
TOOL_DISPATCH["project_tasks_full"] = (None, _project_tasks_full_handler)
TOOL_DISPATCH["inbox_list"] = (None, _inbox_list_handler)
# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _doctor_run(timeout: int = 10) -> dict:
    """T0.13 wrapper — delegates to doctor.doctor_run with SKILL_VERSION injected.
    Kept as a thin shim so existing argparse handler (--doctor) is unchanged.
    """
    return _doctor_run_impl(skill_version=SKILL_VERSION, timeout=timeout)




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
        "--doctor", action="store_true",
        help="Run read-only self-check (no side effects)",
    )
    parser.add_argument(
        "--verify-cache", action="store_true",
        help="Verify references/*.json caches: schema_version, complete=True, no legacy",
    )
    parser.add_argument(
        "--verify-metadata", action="store_true",
        help="Verify tools.json matches runtime TOOL_CATALOG (no drift)",
    )
    parser.add_argument(
        "--verify-api", action="store_true",
        help="Read-only API smoke check — endpoints reachable, schemas match observed shapes",
    )

    cli_args = parser.parse_args()

    # -- --verify-api (T7.1) — read-only live API smoke check ---------------
    if cli_args.verify_api:
        result: dict = {
            "status": "ok",
            "skill_version": SKILL_VERSION,
            "checks": [],
        }
        any_fail = False
        try:
            cfg = load_config()
        except FileNotFoundError as exc:
            print(json.dumps({
                "status": "fail",
                "skill_version": SKILL_VERSION,
                "detail": str(exc),
            }, indent=2, ensure_ascii=False))
            sys.exit(2)

        client = SingularityClient(cfg["base_url"], cfg["token"])

        # Probe each canonical v2 endpoint with maxCount=1 (minimum impact)
        endpoints_to_probe = [
            ("/v2/api-json", "openapi schema"),
            ("/v2/project", "list projects"),
            ("/v2/task", "list tasks"),
            ("/v2/tag", "list tags"),
            ("/v2/note", "list notes (per Decision A)"),
            ("/v2/task-group", "list task groups"),
        ]
        for path, desc in endpoints_to_probe:
            check: dict = {"endpoint": path, "purpose": desc}
            try:
                if path == "/v2/api-json":
                    body = client.get(path)
                    ok = isinstance(body, dict) and (
                        "openapi" in body or "swagger" in body
                    )
                    check["status"] = "ok" if ok else "fail"
                    check["detail"] = (
                        f"OpenAPI {body.get('openapi', body.get('swagger', '?'))}"
                        if ok else "did not return OpenAPI document"
                    )
                elif path == "/v2/note":
                    # T0.3 capability check — wrapper key 'notes' (Decision A)
                    body = client.get(path, params={"maxCount": 1})
                    ok = isinstance(body, dict) and "notes" in body \
                         and isinstance(body["notes"], list)
                    check["status"] = "ok" if ok else "fail"
                    check["detail"] = (
                        f"wrapper 'notes' present, {len(body['notes'])} sample"
                        if ok else f"unexpected shape: {list(body.keys()) if isinstance(body, dict) else type(body).__name__}"
                    )
                else:
                    body = client.get(path, params={"maxCount": 1})
                    check["status"] = "ok" if isinstance(body, (dict, list)) else "fail"
                    check["detail"] = (
                        f"reachable, returned {type(body).__name__}"
                        if check["status"] == "ok"
                        else f"unexpected response type {type(body).__name__}"
                    )
            except Exception as exc:  # noqa: BLE001
                check["status"] = "fail"
                check["detail"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            if check["status"] == "fail":
                any_fail = True
            result["checks"].append(check)

        if any_fail:
            result["status"] = "fail"
        result["summary"] = (
            f"{sum(1 for c in result['checks'] if c['status']=='ok')}/"
            f"{len(result['checks'])} endpoints healthy"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["status"] == "ok" else 1)

    # -- --verify-metadata (T4.7) — read-only check on tools.json drift -----
    if cli_args.verify_metadata:
        import subprocess
        try:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "regen_metadata.py"),
                 "--check"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({
                "status": "fail",
                "skill_version": SKILL_VERSION,
                "detail": f"could not run regen_metadata.py --check: "
                         f"{type(exc).__name__}: {exc}",
            }, indent=2, ensure_ascii=False))
            sys.exit(1)
        in_sync = (result.returncode == 0)
        out: dict = {
            "status": "ok" if in_sync else "fail",
            "skill_version": SKILL_VERSION,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        sys.exit(0 if in_sync else 1)

    # -- --verify-cache (T3.14) — read-only check on cache integrity ---------
    if cli_args.verify_cache:
        result = {"status": "ok", "skill_version": SKILL_VERSION, "checks": []}
        cache_files = ("projects.json", "tags.json", "task_groups.json")
        any_fail = False
        for fname in cache_files:
            fpath = REFS_DIR / fname
            check: dict = {"file": fname}
            if not fpath.exists():
                check["status"] = "fail"
                check["detail"] = "missing"
                any_fail = True
            else:
                info = read_cache(fpath)
                if info is None:
                    check["status"] = "fail"
                    check["detail"] = "unreadable or invalid JSON"
                    any_fail = True
                elif info["is_legacy"]:
                    check["status"] = "fail"
                    check["detail"] = "legacy format (no _meta) — run rebuild_references"
                    any_fail = True
                else:
                    meta = info["meta"]
                    if not meta.get("complete"):
                        check["status"] = "fail"
                        check["detail"] = f"_meta.complete=False ({meta.get('total_items')} items, partial fetch)"
                        any_fail = True
                    else:
                        check["status"] = "ok"
                        check["detail"] = (
                            f"schema_v{meta.get('schema_version')}, "
                            f"{meta.get('total_items')} items, "
                            f"generated_at={meta.get('generated_at')}"
                        )
            result["checks"].append(check)
        if any_fail:
            result["status"] = "fail"
        result["summary"] = (
            f"{sum(1 for c in result['checks'] if c['status']=='ok')}/"
            f"{len(result['checks'])} caches healthy"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        sys.exit(0 if result["status"] == "ok" else 1)

    # -- --doctor (must run early, before any auto-refresh side effects) ----
    if cli_args.doctor:
        result = _doctor_run()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        # Exit code: 0 ok, 1 any check failed, 2 config missing/invalid
        if result["status"] == "ok":
            sys.exit(0)
        if any(c["name"] == "config_exists" and c["status"] == "fail"
               for c in result["checks"]):
            sys.exit(2)
        sys.exit(1)

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
        # T4.3 — translate Python type names to JSON Schema draft-07 type names.
        # Closes Drift 4 (known-drifts.md). Map: int→integer, str→string,
        # float→number, bool→boolean, list→array (with items), object (with properties).
        TYPE_MAP = {
            "int": "integer",
            "str": "string",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "object": "object",
            # passthrough for already-valid names
            "integer": "integer", "string": "string", "number": "number",
            "boolean": "boolean", "array": "array",
        }

        def _build_param_schema(v: dict) -> dict:
            t = TYPE_MAP.get(v.get("type", "string"), "string")
            ps: dict = {
                "type": t,
                "description": v.get("desc", ""),
            }
            # JSON Schema draft-07 requires `items` for arrays and `properties`
            # for objects. Defensive defaults — concrete schemas can be
            # overridden in T4.1 catalog.py migration.
            if t == "array":
                ps["items"] = v.get("items", {"type": "string"})
            if t == "object":
                ps["properties"] = v.get("properties", {})
                if "additionalProperties" in v:
                    ps["additionalProperties"] = v["additionalProperties"]
            if "default" in v:
                ps["default"] = v["default"]
            if "enum" in v:
                ps["enum"] = v["enum"]
            return ps

        schema = {
            "name": name,
            "description": meta["desc"],
            "inputSchema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    k: _build_param_schema(v)
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

            migration_error = _check_description_migration(tool_name)
            if migration_error:
                print(json.dumps(migration_error, indent=2, ensure_ascii=False))
                return

            _check_and_refresh_cache(cfg)

            if (
                cfg.get("read_only")
                and tool_name in WRITE_TOOLS
                and tool_name not in LOCAL_WRITE_TOOLS
            ):
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
        except StructuredError as exc:
            print(json.dumps(exc.payload, indent=2, ensure_ascii=False))
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # -- no args ------------------------------------------------------------
    parser.print_help()


if __name__ == "__main__":
    main()
