"""Read and write values in nested dict/list structures by dot paths."""

from __future__ import annotations

import re
from typing import Any

_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def get_by_path(root: Any, path: str) -> Any:
    current = root
    for part, index in _parse_tokens(path):
        if index is not None:
            if not isinstance(current, list):
                raise KeyError(path)
            current = current[int(index)]
        else:
            if not isinstance(current, dict) or part not in current:
                raise KeyError(path)
            current = current[part]
    return current


def resolve_parent(root: Any, path: str) -> tuple[Any, str | int | None]:
    """Resolve everything but the last segment, returning (container, key).

    Lets a caller replace the array a path points at: ``container[key] = new_list``.
    Returns ``(None, None)`` when the parent doesn't exist.
    """
    tokens = _parse_tokens(path)
    if not tokens:
        return None, None
    parent_path = path[: path.rindex(_last_segment(path))].rstrip(".[")
    parent = resolve_path(root, parent_path) if parent_path else root
    part, index = tokens[-1]
    key: str | int | None = int(index) if index is not None else part
    if isinstance(parent, list) and isinstance(key, str) and key.isdigit():
        key = int(key)
    if parent is None:
        return None, None
    return parent, key


def _last_segment(path: str) -> str:
    for match in reversed(list(_PATH_TOKEN.finditer(path))):
        return match.group(0)
    return path


def resolve_path(root: Any, path: str) -> Any:
    """Like ``get_by_path`` but tolerant, for config-supplied paths.

    Accepts a bare number as a list index (``body.body.0.accommodations``) as well as
    bracket form (``body.body[0]``), and returns ``None`` instead of raising when the
    path doesn't exist — a supplier's mutation config is user input, so a wrong path
    should surface as "no packages found", not a KeyError from deep in the mutator.
    """
    if not path:
        return None
    current = root
    for part, index in _parse_tokens(path):
        key = index if index is not None else part
        if key is None:
            return None
        if isinstance(current, list):
            if not str(key).isdigit():
                return None
            position = int(key)
            if position >= len(current):
                return None
            current = current[position]
        elif isinstance(current, dict):
            if key not in current:
                return None
            current = current[key]
        else:
            return None
    return current


def set_by_path(root: Any, path: str, value: Any) -> None:
    tokens = list(_parse_tokens(path))
    current = root
    for part, index in tokens[:-1]:
        if index is not None:
            current = current[int(index)]
        else:
            current = current[part]
    last_part, last_index = tokens[-1]
    if last_index is not None:
        current[int(last_index)] = value
    else:
        current[last_part] = value


def replace_string_values(node: Any, old: str, new: str) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and old in value:
                node[key] = value.replace(old, new)
            else:
                replace_string_values(value, old, new)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            if isinstance(item, str) and old in item:
                node[index] = item.replace(old, new)
            else:
                replace_string_values(item, old, new)


def _parse_tokens(path: str) -> list[tuple[str | None, str | None]]:
    tokens: list[tuple[str | None, str | None]] = []
    for match in _PATH_TOKEN.finditer(path):
        part, index = match.groups()
        if index is not None:
            tokens.append((None, index))
        else:
            tokens.append((part, None))
    return tokens
