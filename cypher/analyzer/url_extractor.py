"""Structured extraction of Django URL patterns from parsed file records."""

from __future__ import annotations

import ast
import hashlib
import re
from typing import Any


def _stable_id(kind: str, *parts: object) -> str:
    value = "\0".join((kind, *(str(part) for part in parts)))
    return f"{kind}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


def _clean_string_literal(value: str | None) -> str | None:
    if not value or value == "<non-literal>":
        return None
    try:
        evaluated = ast.literal_eval(value)
        if isinstance(evaluated, str):
            return evaluated
    except (ValueError, SyntaxError):
        pass
    # Fallback to stripping quotes
    stripped = value.strip()
    if (stripped.startswith("'") and stripped.endswith("'")) or (
        stripped.startswith('"') and stripped.endswith('"')
    ):
        return stripped[1:-1]
    return stripped


def _extract_include_target(view_ref: str | None) -> str | None:
    if not view_ref:
        return None
    # Matches include('users.urls') or include("users.urls") or include(('users.urls', ...))
    match = re.search(r"""include\(\s*['"]([^'"]+)['"]""", view_ref)
    if match:
        return match.group(1)
    return None


def extract_url_patterns(file_record: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract structured Django URLPattern records from a parsed file record."""
    file_path = file_record.get("path", "")
    
    # 1. Look for app_name in globals
    namespace: str | None = None
    for global_var in file_record.get("globals", []):
        if global_var.get("name") == "app_name":
            namespace = _clean_string_literal(global_var.get("value"))
            break

    patterns: list[dict[str, Any]] = []
    seen_lines: set[int] = set()

    framework_hints = file_record.get("framework_hints", [])
    url_hints = [h for h in framework_hints if h.get("kind") == "url_pattern"]

    # First pass: path() / re_path() calls
    for hint in url_hints:
        hint_name = hint.get("name", "")
        if hint_name in ("path", "re_path"):
            line = hint.get("line", 1)
            seen_lines.add(line)
            details = hint.get("details", {})
            route = details.get("route")
            view_ref = details.get("view")
            url_name = details.get("name")
            pattern_namespace = details.get("namespace") or namespace
            
            is_include = False
            include_target: str | None = None
            if view_ref and "include(" in view_ref:
                is_include = True
                include_target = _extract_include_target(view_ref)
            elif details.get("is_include"):
                is_include = True
                include_target = details.get("include_target")

            pattern_id = _stable_id("url_pattern", file_path, route or "", line)
            patterns.append(
                {
                    "id": pattern_id,
                    "file_path": file_path,
                    "route": route,
                    "view_ref": view_ref,
                    "url_name": url_name,
                    "namespace": pattern_namespace,
                    "is_include": is_include,
                    "include_target": include_target,
                    "line": line,
                    "confidence": hint.get("confidence", "high"),
                }
            )

    # Second pass: standalone include() not captured by a path() on the same line
    for hint in url_hints:
        hint_name = hint.get("name", "")
        line = hint.get("line", 1)
        if hint_name == "include" and line not in seen_lines:
            seen_lines.add(line)
            details = hint.get("details", {})
            raw_target = details.get("include", "")
            include_target = _clean_string_literal(raw_target)
            if not include_target and raw_target:
                match = re.search(r"""['"]([^'"]+)['"]""", raw_target)
                if match:
                    include_target = match.group(1)
            pattern_id = _stable_id("url_pattern", file_path, "include", line)
            patterns.append(
                {
                    "id": pattern_id,
                    "file_path": file_path,
                    "route": None,
                    "view_ref": f"include({raw_target})" if raw_target else "include()",
                    "url_name": None,
                    "namespace": namespace,
                    "is_include": True,
                    "include_target": include_target,
                    "line": line,
                    "confidence": hint.get("confidence", "high"),
                }
            )

    patterns.sort(key=lambda p: (p["line"], p["route"] or ""))
    return patterns
