"""JSON extraction and light validation helpers for agent outputs."""
from __future__ import annotations

import json
from typing import Any


def extract_first_json_object(text: str) -> dict[str, Any] | None:
    """Extract and decode the first top-level JSON object in a string."""
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                snippet = text[start : idx + 1]
                try:
                    obj = json.loads(snippet)
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None

    return None


def ensure_list(value: Any) -> list[Any]:
    """Return a list for list-like outputs, otherwise an empty list."""
    return value if isinstance(value, list) else []


def ensure_dict(value: Any) -> dict[str, Any]:
    """Return a dict for dict-like outputs, otherwise an empty dict."""
    return value if isinstance(value, dict) else {}
