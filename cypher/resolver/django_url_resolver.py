"""Resolve Django URL patterns to view functions/classes across the repository."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

from cypher.analyzer.url_extractor import extract_url_patterns
from cypher.resolver.import_resolver import ImportResolver
from cypher.resolver.symbol_index import SymbolIndex


def _stable_id(kind: str, *parts: object) -> str:
    value = "\0".join((kind, *(str(part) for part in parts)))
    return f"{kind}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


@dataclass
class UrlRelationship:
    id: str
    source_file: str  # the urls.py file
    source_module: str

    rel_type: str  # "ROUTES_TO" | "INCLUDES"

    route: str | None  # URL path string
    url_name: str | None
    namespace: str | None

    # For ROUTES_TO:
    view_expression: str | None  # original expression
    target_entity_id: str | None  # resolved view function entity ID
    target_qualified: str | None
    target_file: str | None

    # For INCLUDES:
    include_target: str | None  # "users.urls" module string
    include_file_id: str | None  # resolved file entity ID

    confidence: str
    evidence: str
    line: int


class DjangoUrlResolver:
    """Discovers and resolves all URL patterns and includes across the codebase."""

    def __init__(self, index: SymbolIndex, import_resolver: ImportResolver) -> None:
        self.index = index
        self.import_resolver = import_resolver

    def resolve_urls(
        self, all_files: dict[str, dict[str, Any]] | list[dict[str, Any]]
    ) -> list[UrlRelationship]:
        """Find all urlpatterns across all files, resolve view references and includes."""
        if isinstance(all_files, dict):
            files_list = list(all_files.values())
        else:
            files_list = all_files

        relationships: list[UrlRelationship] = []

        for file_record in files_list:
            patterns = extract_url_patterns(file_record)
            if not patterns:
                continue

            source_file = file_record.get("path", "")
            source_module = file_record.get("module", "")
            import_map = self.import_resolver.build_file_import_map(file_record)

            for pattern in patterns:
                rel = self._resolve_pattern(
                    pattern=pattern,
                    source_file=source_file,
                    source_module=source_module,
                    import_map=import_map,
                    file_record=file_record,
                )
                if rel is not None:
                    relationships.append(rel)

        return relationships

    def _resolve_pattern(
        self,
        pattern: dict[str, Any],
        source_file: str,
        source_module: str,
        import_map: dict[str, str],
        file_record: dict[str, Any],
    ) -> UrlRelationship:
        route = pattern.get("route")
        view_ref = pattern.get("view_ref")
        url_name = pattern.get("url_name")
        namespace = pattern.get("namespace")
        line = pattern.get("line", 1)
        is_include = pattern.get("is_include", False)
        include_target = pattern.get("include_target")

        # -------------------------------------------------------------------
        # 1. INCLUDES Relationship
        # -------------------------------------------------------------------
        if is_include:
            target_mod = None
            if include_target:
                target_mod = self.index.lookup_module(include_target)

            if target_mod is not None:
                rel_id = _stable_id("rel_includes", source_file, include_target or "", line)
                return UrlRelationship(
                    id=rel_id,
                    source_file=source_file,
                    source_module=source_module,
                    rel_type="INCLUDES",
                    route=route,
                    url_name=url_name,
                    namespace=namespace,
                    view_expression=view_ref,
                    target_entity_id=target_mod["id"],
                    target_qualified=target_mod["qualified_name"],
                    target_file=target_mod["file_path"],
                    include_target=include_target,
                    include_file_id=target_mod["id"],
                    confidence="high",
                    evidence=f"include target '{include_target}' resolved to module in {target_mod['file_path']}",
                    line=line,
                )
            else:
                rel_id = _stable_id("rel_includes", source_file, include_target or "external", line)
                return UrlRelationship(
                    id=rel_id,
                    source_file=source_file,
                    source_module=source_module,
                    rel_type="INCLUDES",
                    route=route,
                    url_name=url_name,
                    namespace=namespace,
                    view_expression=view_ref,
                    target_entity_id=None,
                    target_qualified=include_target,
                    target_file=None,
                    include_target=include_target,
                    include_file_id=None,
                    confidence="high" if (include_target and include_target.startswith("django.")) else "low",
                    evidence=f"External or unresolved include target '{include_target}'",
                    line=line,
                )

        # -------------------------------------------------------------------
        # 2. ROUTES_TO Relationship
        # -------------------------------------------------------------------
        clean_view = view_ref or ""
        if clean_view.endswith(".as_view()"):
            clean_view = clean_view[:-9]

        resolved_entity = None
        target_qualified = None

        if "." in clean_view:
            rec, _, attr = clean_view.partition(".")
            if rec in import_map:
                expanded_rec = import_map[rec]
                target_qualified = f"{expanded_rec}.{attr}"
                resolved_entity = self.index.lookup_qualified(target_qualified)
                if resolved_entity is None:
                    resolved_entity = self.index.lookup_in_module(expanded_rec, attr)
            else:
                target_qualified = f"{source_module}.{clean_view}" if source_module else clean_view
                resolved_entity = self.index.lookup_qualified(target_qualified)
                if resolved_entity is None:
                    resolved_entity = self.index.lookup_in_module(source_module, clean_view)
        else:
            if clean_view in import_map:
                target_qualified = import_map[clean_view]
                resolved_entity = self.index.lookup_qualified(target_qualified)
            elif clean_view:
                target_qualified = f"{source_module}.{clean_view}" if source_module else clean_view
                resolved_entity = self.index.lookup_in_module(source_module, clean_view)

        if resolved_entity is not None:
            rel_id = _stable_id("rel_routes_to", source_file, resolved_entity["qualified_name"], route or "", line)
            return UrlRelationship(
                id=rel_id,
                source_file=source_file,
                source_module=source_module,
                rel_type="ROUTES_TO",
                route=route,
                url_name=url_name,
                namespace=namespace,
                view_expression=view_ref,
                target_entity_id=resolved_entity["id"],
                target_qualified=resolved_entity["qualified_name"],
                target_file=resolved_entity["file_path"],
                include_target=None,
                include_file_id=None,
                confidence="high",
                evidence=f"Route '{route}' resolves to {resolved_entity['kind']} '{resolved_entity['qualified_name']}'",
                line=line,
            )
        else:
            rel_id = _stable_id("rel_routes_to", source_file, clean_view, route or "", line)
            return UrlRelationship(
                id=rel_id,
                source_file=source_file,
                source_module=source_module,
                rel_type="ROUTES_TO",
                route=route,
                url_name=url_name,
                namespace=namespace,
                view_expression=view_ref,
                target_entity_id=None,
                target_qualified=target_qualified or clean_view,
                target_file=None,
                include_target=None,
                include_file_id=None,
                confidence="low",
                evidence=f"View reference '{view_ref}' could not be resolved to an internal entity",
                line=line,
            )
