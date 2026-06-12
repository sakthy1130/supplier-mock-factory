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
