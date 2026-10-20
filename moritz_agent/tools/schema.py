# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Argument validation against the small JSON-schema subset the tools use (AGENT-03).

Models are sloppy with types ("5" instead of 5), so numbers, integers and booleans are coerced from
their string form. Unknown arguments are dropped, missing required ones and values outside
``enum`` / ``minimum`` / ``maximum`` / ``maxLength`` are reported in German for the model to correct.
"""

from __future__ import annotations

from typing import Any

_TRUE = {"true", "ja", "1"}
_FALSE = {"false", "nein", "0"}


def validate(args: Any, schema: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Cleaned arguments and a list of problems (empty = valid)."""
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return {}, ["Die Argumente müssen ein JSON-Objekt sein."]
    properties: dict[str, Any] = schema.get("properties", {})
    clean: dict[str, Any] = {}
    problems: list[str] = []
    for name, spec in properties.items():
        if name not in args or args[name] is None:
            if "default" in spec:
                clean[name] = spec["default"]
            continue
        value, problem = _check(name, args[name], spec)
        if problem:
            problems.append(problem)
        else:
            clean[name] = value
    for name in schema.get("required", []):
        if name not in clean and not any(p.startswith(f"'{name}'") for p in problems):
            problems.append(f"Das Argument '{name}' fehlt.")
    return clean, problems


def _check(name: str, value: Any, spec: dict[str, Any]) -> tuple[Any, str | None]:
    kind = spec.get("type")
    if kind == "string":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            return None, f"'{name}' muss ein Text sein."
        value = value.strip()
        if len(value) > spec.get("maxLength", 500):
            return None, f"'{name}' ist zu lang (höchstens {spec.get('maxLength', 500)} Zeichen)."
        if len(value) < spec.get("minLength", 0):
            return None, f"'{name}' darf nicht leer sein."
    elif kind in {"integer", "number"}:
        value, problem = _number(name, value, kind)
        if problem:
            return None, problem
        if "minimum" in spec and value < spec["minimum"]:
            return None, f"'{name}' muss mindestens {spec['minimum']} sein."
        if "maximum" in spec and value > spec["maximum"]:
            return None, f"'{name}' darf höchstens {spec['maximum']} sein."
    elif kind == "boolean":
        if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
            value = value.strip().lower() in _TRUE
        if not isinstance(value, bool):
            return None, f"'{name}' muss wahr oder falsch sein."
    elif kind == "array":
        if not isinstance(value, list):
            return None, f"'{name}' muss eine Liste sein."
    elif kind == "object" and not isinstance(value, dict):
        return None, f"'{name}' muss ein Objekt sein."
    if "enum" in spec and value not in spec["enum"]:
        allowed = ", ".join(str(item) for item in spec["enum"])
        return None, f"'{name}' muss eines von diesen sein: {allowed}."
    return value, None


def _number(name: str, value: Any, kind: str) -> tuple[Any, str | None]:
    wording = "eine ganze Zahl" if kind == "integer" else "eine Zahl"
    if isinstance(value, bool):
        return None, f"'{name}' muss {wording} sein."
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError:
            return None, f"'{name}' muss {wording} sein."
    if not isinstance(value, (int, float)):
        return None, f"'{name}' muss {wording} sein."
    if kind == "integer":
        if isinstance(value, float) and not value.is_integer():
            return None, f"'{name}' muss {wording} sein."
        return int(value), None
    return value, None
