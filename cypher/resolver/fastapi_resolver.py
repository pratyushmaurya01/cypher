"""Resolve FastAPI route decorators and include_router() calls across the repository.

The existing ast_parser already emits ``framework_hints`` with ``framework="fastapi"``
and ``kind="route"`` for every function decorated via a FastAPI app or APIRouter.
This resolver consumes those hints plus the raw call list (for include_router) to
produce ``UrlRelationship`` objects compatible with the rest of the pipeline.

Resolution strategy
-------------------
ROUTES_TO
    For each ``framework_hints`` entry where ``framework="fastapi"`` and
    ``kind="route"``, look up the function entity in the SymbolIndex by module +
    function name.  Use ``details.path`` and ``details.methods`` from the hint.

INCLUDES  (include_router)
    Scan each file's ``calls`` list for calls whose ``base_name == "include_router"``.
    The call record does not store arguments, so we can only confirm that an
    include_router call exists in the file.  We try a best-effort resolution:
    if the file's import map contains a ``router`` attribute originating from
    another module, we produce a high-confidence relationship; otherwise we emit
    a low-confidence placeholder so the information is not silently lost.
"""

from __future__ import annotations

import hashlib
from typing import Any

from cypher.resolver.django_url_resolver import UrlRelationship
from cypher.resolver.import_resolver import ImportResolver
from cypher.resolver.symbol_index import SymbolIndex


def _stable_id(kind: str, *parts: object) -> str:
    value = "\0".join((kind, *(str(p) for p in parts)))
    return f"{kind}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


class FastAPIResolver:
    """Discovers FastAPI ROUTES_TO and include_router INCLUDES relationships."""

    def __init__(self, index: SymbolIndex, import_resolver: ImportResolver) -> None:
        self.index = index
        self.import_resolver = import_resolver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_routes(self, all_files: list[dict[str, Any]]) -> list[UrlRelationship]:
        """Return ROUTES_TO relationships for all FastAPI endpoint functions."""
        results: list[UrlRelationship] = []
        for file_record in all_files:
            results.extend(self._routes_for_file(file_record))
        return results

    def resolve_includes(self, all_files: list[dict[str, Any]]) -> list[UrlRelationship]:
        """Return INCLUDES relationships for include_router() calls."""
        results: list[UrlRelationship] = []
        for file_record in all_files:
            results.extend(self._includes_for_file(file_record, all_files))
        return results

    def resolve_all(self, all_files: list[dict[str, Any]]) -> list[UrlRelationship]:
        """Convenience: ROUTES_TO + INCLUDES combined."""
        return self.resolve_routes(all_files) + self.resolve_includes(all_files)

    # ------------------------------------------------------------------
    # ROUTES_TO
    # ------------------------------------------------------------------

    def _routes_for_file(self, file_record: dict[str, Any]) -> list[UrlRelationship]:
        results: list[UrlRelationship] = []
        module_name = file_record.get("module", "")
        file_path = file_record.get("path", "")

        for hint in file_record.get("framework_hints", []):
            if hint.get("framework") != "fastapi" or hint.get("kind") != "route":
                continue

            func_name: str = hint["name"]
            line: int = hint.get("line", 1)
            details: dict[str, Any] = hint.get("details", {})
            route: str | None = details.get("path")
            http_methods: list[str] = details.get("methods", [])

            # Resolve the function entity
            entity = self.index.lookup_in_module(module_name, func_name)

            rel_id = _stable_id("rel_fastapi_route", file_path, func_name, route or "", line)

            if entity is not None:
                results.append(UrlRelationship(
                    id=rel_id,
                    source_file=file_path,
                    source_module=module_name,
                    rel_type="ROUTES_TO",
                    route=route,
                    url_name=None,           # FastAPI uses path tags, not named URL patterns
                    namespace=None,
                    view_expression=func_name,
                    target_entity_id=entity["id"],
                    target_qualified=entity["qualified_name"],
                    target_file=entity["file_path"],
                    include_target=None,
                    include_file_id=None,
                    confidence=hint.get("confidence", "high"),
                    evidence=f"fastapi route {http_methods} '{route}' -> {entity['qualified_name']} | {hint.get('evidence', '')}",
                    line=line,
                ))
            else:
                # Function defined in the file but not yet indexed — emit low-confidence
                results.append(UrlRelationship(
                    id=rel_id,
                    source_file=file_path,
                    source_module=module_name,
                    rel_type="ROUTES_TO",
                    route=route,
                    url_name=None,
                    namespace=None,
                    view_expression=func_name,
                    target_entity_id=None,
                    target_qualified=f"{module_name}.{func_name}" if module_name else func_name,
                    target_file=file_path,
                    include_target=None,
                    include_file_id=None,
                    confidence="low",
                    evidence=f"fastapi route hint for '{func_name}' but entity not found in index | {hint.get('evidence', '')}",
                    line=line,
                ))
        return results

    # ------------------------------------------------------------------
    # INCLUDES (include_router)
    # ------------------------------------------------------------------

    def _includes_for_file(
        self,
        file_record: dict[str, Any],
        all_files: list[dict[str, Any]],
    ) -> list[UrlRelationship]:
        """Find include_router() calls and try to resolve their targets."""
        results: list[UrlRelationship] = []
        file_path = file_record.get("path", "")
        module_name = file_record.get("module", "")
        import_map = self.import_resolver.build_file_import_map(file_record)

        for call in file_record.get("calls", []):
            if call.get("base_name") != "include_router":
                continue

            line: int = call.get("line", 1)
            # The receiver of include_router (e.g. "app" or "router")
            receiver: str | None = call.get("receiver")

            # Try to find a router module that was imported into this file.
            # We look for any import whose local name resolves to a module
            # containing FastAPI route hints.
            target_entity, target_qualified, target_file_path, target_module = \
                self._find_included_router_target(file_record, import_map, all_files)

            rel_id = _stable_id("rel_fastapi_include", file_path, target_qualified or "unknown", line)

            results.append(UrlRelationship(
                id=rel_id,
                source_file=file_path,
                source_module=module_name,
                rel_type="INCLUDES",
                route=None,       # prefix not recoverable from call record alone
                url_name=None,
                namespace=None,
                view_expression=None,
                target_entity_id=target_entity["id"] if target_entity else None,
                target_qualified=target_qualified,
                target_file=target_file_path,
                include_target=target_module,
                include_file_id=target_entity["id"] if target_entity else None,
                confidence="high" if target_entity else "low",
                evidence=(
                    f"fastapi include_router() call by '{receiver}' -> {target_module or 'unknown router'}"
                    if target_entity
                    else f"fastapi include_router() call detected (receiver='{receiver}') but target router module unresolved"
                ),
                line=line,
            ))
        return results

    def _find_included_router_target(
        self,
        file_record: dict[str, Any],
        import_map: dict[str, str],
        all_files: list[dict[str, Any]],
    ) -> tuple[dict | None, str | None, str | None, str | None]:
        """
        Heuristic: find which module in the repo defines an APIRouter that is
        imported into this file.  Returns (entity, qualified_name, file_path, module).
        """
        # Build a quick lookup: module_name -> file_record for FastAPI-router files
        router_modules: dict[str, dict[str, Any]] = {}
        for f in all_files:
            has_router = any(
                h.get("framework") == "fastapi" and h.get("kind") == "route"
                for h in f.get("framework_hints", [])
            )
            if has_router and f.get("module"):
                router_modules[f["module"]] = f

        # Check import_map: if any imported qualified_name starts with a router module
        for local_name, qualified in import_map.items():
            # e.g. local_name="users", qualified="routers.users"
            mod_entity = self.index.lookup_module(qualified)
            if mod_entity and qualified in router_modules:
                return mod_entity, qualified, mod_entity["file_path"], qualified

        # Fallback: return None
        return None, None, None, None
