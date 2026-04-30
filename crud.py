"""Generic CRUD handlers for singularity skill resources."""

from __future__ import annotations

from urllib.parse import quote

from client import SingularityClient
from resources import RESOURCES


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


__all__ = [
    "_coerce",
    "_list_handler",
    "_get_handler",
    "_create_handler",
    "_update_handler",
    "_delete_handler",
    "_time_stat_bulk_delete_handler",
]
