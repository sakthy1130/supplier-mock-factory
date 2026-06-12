"""Shared JSON deep-walk helpers for supplier plugins."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Callable


def deep_copy(obj: Any) -> Any:
    return copy.deepcopy(obj)


def walk_nodes(node: Any) -> list[Any]:
    """Yield every dict/list node in a JSON tree (including root)."""
    nodes = [node]
    if isinstance(node, dict):
        for value in node.values():
            nodes.extend(walk_nodes(value))
    elif isinstance(node, list):
        for item in node:
            nodes.extend(walk_nodes(item))
    return nodes


def update_fields_recursive(
    node: Any,
    field_updates: dict[str, Callable[[Any], Any]],
) -> None:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key in field_updates:
                node[key] = field_updates[key](value)
            else:
                update_fields_recursive(value, field_updates)
    elif isinstance(node, list):
        for item in node:
            update_fields_recursive(item, field_updates)


def collect_field_values(node: Any, field_name: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == field_name:
                found.append(value)
            found.extend(collect_field_values(value, field_name))
    elif isinstance(node, list):
        for item in node:
            found.extend(collect_field_values(item, field_name))
    return found


def replace_in_json_strings(node: Any, replacements: list[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                updated = value
                for old, new in replacements:
                    updated = updated.replace(old, new)
                node[key] = updated
            else:
                replace_in_json_strings(value, replacements)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            if isinstance(item, str):
                updated = item
                for old, new in replacements:
                    updated = updated.replace(old, new)
                node[index] = updated
            else:
                replace_in_json_strings(item, replacements)


def replace_url_query_param(url: str, param: str, value: str) -> str:
    pattern = rf"({re.escape(param)}=)[^&]*"
    if re.search(pattern, url):
        return re.sub(pattern, rf"\g<1>{value}", url)
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{param}={value}"
