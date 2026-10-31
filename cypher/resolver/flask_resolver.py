"""Resolve Flask route decorators and register_blueprint() calls across the repository.

The existing ast_parser already emits ``framework_hints`` with ``framework="flask"``
and ``kind="route"`` for every function decorated via a Flask app or Blueprint.
This resolver consumes those hints plus the call list (with static arguments)
to produce ``UrlRelationship`` objects compatible with the rest of the pipeline.
"""

from __future__ import annotations

import ast
import hashlib
from typing import Any

from cypher.resolver.django_url_resolver import UrlRelationship
from cypher.resolver.import_resolver import ImportResolver
from cypher.resolver.symbol_index import SymbolIndex


def _stable_id(kind: str, *parts: object) -> str:
    value = "\0".join((kind, *(str(p) for p in parts)))
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
    stripped = value.strip()
    if (stripped.startswith("'") and stripped.endswith("'")) or (
        stripped.startswith('"') and stripped.endswith('"')
    ):
        return stripped[1:-1]
    return stripped


class FlaskResolver:
    """Discovers Flask ROUTES_TO and register_blueprint INCLUDES relationships."""

    def __init__(self, index: SymbolIndex, import_resolver: ImportResolver) -> None:
        self.index = index
        self.import_resolver = import_resolver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_routes(self, all_files: list[dict[str, Any]]) -> list[UrlRelationship]:
        """Return ROUTES_TO relationships for all Flask route functions."""
        results: list[UrlRelationship] = []
        for file_record in all_files:
            results.extend(self._routes_for_file(file_record))
        return results

    def resolve_blueprints(self, all_files: list[dict[str, Any]]) -> list[UrlRelationship]:
        """Return INCLUDES relationships for register_blueprint() calls."""
        results: list[UrlRelationship] = []
        for file_record in all_files:
            results.extend(self._blueprints_for_file(file_record, all_files))
        return results

    def resolve_all(self, all_files: list[dict[str, Any]]) -> list[UrlRelationship]:
        """Convenience: ROUTES_TO + INCLUDES combined."""
        return self.resolve_routes(all_files) + self.resolve_blueprints(all_files)

    # ------------------------------------------------------------------
    # ROUTES_TO
    # ------------------------------------------------------------------

    def _routes_for_file(self, file_record: dict[str, Any]) -> list[UrlRelationship]:
        results: list[UrlRelationship] = []
        module_name = file_record.get("module", "")
        file_path = file_record.get("path", "")

        for hint in file_record.get("framework_hints", []):
            if hint.get("framework") != "flask" or hint.get("kind") != "route":
                continue

            func_name: str = hint["name"]
            line: int = hint.get("line", 1)
            details: dict[str, Any] = hint.get("details", {})
            route: str | None = details.get("path")
            http_methods: list[str] = details.get("methods", ["GET"])  # Flask default is GET

            # Resolve the function entity in the symbol index
            entity = self.index.lookup_in_module(module_name, func_name)

            rel_id = _stable_id("rel_flask_route", file_path, func_name, route or "", line)

            if entity is not None:
                results.append(
                    UrlRelationship(
                        id=rel_id,
                        source_file=file_path,
                        source_module=module_name,
                        rel_type="ROUTES_TO",
                        route=route,
                        url_name=func_name,  # Flask uses function name as endpoint
                        namespace=None,
                        view_expression=func_name,
                        target_entity_id=entity["id"],
                        target_qualified=entity["qualified_name"],
                        target_file=entity["file_path"],
                        include_target=None,
                        include_file_id=None,
                        confidence=hint.get("confidence", "high"),
                        evidence=f"flask route {http_methods} '{route}' -> {entity['qualified_name']} | {hint.get('evidence', '')}",
                        line=line,
                    )
                )
            else:
                results.append(
                    UrlRelationship(
                        id=rel_id,
                        source_file=file_path,
                        source_module=module_name,
                        rel_type="ROUTES_TO",
                        route=route,
                        url_name=func_name,
                        namespace=None,
                        view_expression=func_name,
                        target_entity_id=None,
                        target_qualified=f"{module_name}.{func_name}" if module_name else func_name,
                        target_file=file_path,
                        include_target=None,
                        include_file_id=None,
                        confidence="low",
                        evidence=f"flask route hint for '{func_name}' but entity not found in index | {hint.get('evidence', '')}",
                        line=line,
                    )
                )
        return results

    # ------------------------------------------------------------------
    # INCLUDES (register_blueprint)
    # ------------------------------------------------------------------

    def _blueprints_for_file(
        self,
        file_record: dict[str, Any],
        all_files: list[dict[str, Any]],
    ) -> list[UrlRelationship]:
        """Find register_blueprint() calls and resolve their targets and prefix."""
        results: list[UrlRelationship] = []
        file_path = file_record.get("path", "")
        module_name = file_record.get("module", "")
        import_map = self.import_resolver.build_file_import_map(file_record)

        for call in file_record.get("calls", []):
            if call.get("base_name") != "register_blueprint":
                continue

            line: int = call.get("line", 1)
            receiver: str | None = call.get("receiver")
            args: list[str] = call.get("arguments", [])
            kwargs: dict[str, str] = call.get("keywords", {})

            bp_arg = args[0] if args else None
            url_prefix = _clean_string_literal(kwargs.get("url_prefix"))

            target_entity, target_qualified, target_file_path, target_module = (
                self._find_blueprint_target(file_record, import_map, all_files, bp_arg)
            )

            # If url_prefix was not specified on register_blueprint(), check Blueprint definition
            if url_prefix is None and target_file_path:
                for f in all_files:
                    if f.get("path") == target_file_path:
                        for bp_call in f.get("calls", []):
                            if bp_call.get("base_name") == "Blueprint":
                                bp_kw = bp_call.get("keywords", {})
                                if "url_prefix" in bp_kw:
                                    url_prefix = _clean_string_literal(bp_kw["url_prefix"])
                                    break
                        break

            rel_id = _stable_id(
                "rel_flask_blueprint", file_path, target_qualified or "unknown", line
            )

            evidence_detail = (
                f"flask register_blueprint({bp_arg or ''}, url_prefix='{url_prefix}') -> {target_module}"
                if target_entity
                else f"flask register_blueprint() call detected (receiver='{receiver}') but target blueprint module unresolved"
            )

            results.append(
                UrlRelationship(
                    id=rel_id,
                    source_file=file_path,
                    source_module=module_name,
                    rel_type="INCLUDES",
                    route=url_prefix,
                    url_name=None,
                    namespace=None,
                    view_expression=bp_arg,
                    target_entity_id=target_entity["id"] if target_entity else None,
                    target_qualified=target_qualified,
                    target_file=target_file_path,
                    include_target=target_module,
                    include_file_id=target_entity["id"] if target_entity else None,
                    confidence="high" if target_entity else "low",
                    evidence=evidence_detail,
                    line=line,
                )
            )
        return results

    def _find_blueprint_target(
        self,
        file_record: dict[str, Any],
        import_map: dict[str, str],
        all_files: list[dict[str, Any]],
        bp_arg: str | None = None,
    ) -> tuple[dict | None, str | None, str | None, str | None]:
        """Resolves target blueprint module from call argument or import map."""
        # 1. Argument-based static resolution
        if bp_arg:
            clean_arg = bp_arg.strip()
            if clean_arg in import_map:
                qualified = import_map[clean_arg]
                parts = qualified.rsplit(".", 1)
                if len(parts) == 2:
                    parent_mod = parts[0]
                    mod_entity = self.index.lookup_module(parent_mod)
                    if mod_entity:
                        return (
                            mod_entity,
                            parent_mod,
                            mod_entity["file_path"],
                            parent_mod,
                        )
                mod_entity = self.index.lookup_module(qualified)
                if mod_entity:
                    return (
                        mod_entity,
                        qualified,
                        mod_entity["file_path"],
                        qualified,
                    )
            elif "." in clean_arg:
                head, _, _ = clean_arg.partition(".")
                if head in import_map:
                    target_mod_name = import_map[head]
                    mod_entity = self.index.lookup_module(target_mod_name)
                    if mod_entity:
                        return (
                            mod_entity,
                            target_mod_name,
                            mod_entity["file_path"],
                            target_mod_name,
                        )

        # 2. Heuristic fallback
        blueprint_modules: dict[str, dict[str, Any]] = {}
        for f in all_files:
            has_bp_route = any(
                h.get("framework") == "flask" and h.get("kind") == "route"
                for h in f.get("framework_hints", [])
            )
            if has_bp_route and f.get("module") and f.get("path") != file_record.get("path"):
                blueprint_modules[f["module"]] = f

        for local_name, qualified in import_map.items():
            mod_entity = self.index.lookup_module(qualified)
            if mod_entity and qualified in blueprint_modules:
                return mod_entity, qualified, mod_entity["file_path"], qualified

        for local_name, qualified in import_map.items():
            parts = qualified.rsplit(".", 1)
            if len(parts) == 2:
                parent_module = parts[0]
                mod_entity = self.index.lookup_module(parent_module)
                if mod_entity and parent_module in blueprint_modules:
                    return (
                        mod_entity,
                        parent_module,
                        mod_entity["file_path"],
                        parent_module,
                    )

        return None, None, None, None
