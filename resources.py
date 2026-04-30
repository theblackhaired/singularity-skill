"""API resource definitions for singularity skill (Iter 6 / T6.4).

Static metadata: paths, body_fields, list_filter_fields per resource.
Used by generic CRUD handlers in cli.py."""

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


__all__ = ["RESOURCES"]
