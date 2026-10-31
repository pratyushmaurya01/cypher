"""Aggregate all resolved entities and relationships into the final graph structure."""

from __future__ import annotations

from collections import Counter
import hashlib
from typing import Any

from cypher.resolver.call_resolver import ResolvedCall
from cypher.resolver.django_url_resolver import UrlRelationship
from cypher.resolver.import_resolver import ImportResolver
from cypher.resolver.symbol_index import SymbolIndex


def _stable_id(kind: str, *parts: object) -> str:
    value = "\0".join((kind, *(str(part) for part in parts)))
    return f"{kind}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


def _extract_http_methods(evidence: str) -> list[str]:
    """Extract HTTP methods from a FastAPI/Flask evidence string like \"['GET', 'POST']\"."""
    import re

    found = re.findall(
        r"\b(GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD|TRACE)\b", evidence.upper()
    )
    return sorted(set(found)) if found else []


def validate_graph(
    entities: list[dict[str, Any]], relationships: list[dict[str, Any]]
) -> list[str]:
    """Validates structural and referential integrity of entities and relationships."""
    errors: list[str] = []
    entity_ids: set[str] = set()

    for ent in entities:
        ent_id = ent.get("id")
        if not ent_id:
            errors.append(f"Entity missing 'id': {ent}")
        elif ent_id in entity_ids:
            errors.append(f"Duplicate entity id: '{ent_id}'")
        else:
            entity_ids.add(ent_id)

    rel_ids: set[str] = set()
    for rel in relationships:
        rel_id = rel.get("id")
        if not rel_id:
            errors.append(f"Relationship missing 'id': {rel}")
        elif rel_id in rel_ids:
            errors.append(f"Duplicate relationship id: '{rel_id}'")
        else:
            rel_ids.add(rel_id)

        source_id = rel.get("source_id")
        target_id = rel.get("target_id")

        if not source_id or source_id not in entity_ids:
            errors.append(
                f"Relationship '{rel_id}' ({rel.get('type')}) has dangling source_id '{source_id}'"
            )
        if not target_id or target_id not in entity_ids:
            errors.append(
                f"Relationship '{rel_id}' ({rel.get('type')}) has dangling target_id '{target_id}'"
            )

    return errors


class RelationshipBuilder:
    """Assembles entities, relationships, unresolved references, and graph statistics."""

    def __init__(self, index: SymbolIndex) -> None:
        self.index = index
        self.import_resolver = ImportResolver(index)

    def build(
        self,
        call_results: list[ResolvedCall],
        url_results: list[UrlRelationship],
        all_files: dict[str, dict[str, Any]] | list[dict[str, Any]],
        root: str | None = None,
    ) -> dict[str, Any]:
        """Returns the final graph-ready structure."""
        if isinstance(all_files, list):
            files_dict = {f.get("path", ""): f for f in all_files}
        else:
            files_dict = all_files

        entities = list(self.index.all_entities())
        entity_ids = {e["id"] for e in entities}
        relationships: list[dict[str, Any]] = []
        seen_rel_keys: set[tuple[str, str, str, Any, Any]] = set()

        def add_entity(entity: dict[str, Any]) -> None:
            if entity["id"] not in entity_ids:
                entity_ids.add(entity["id"])
                entities.append(entity)

        def add_relationship(rel: dict[str, Any]) -> None:
            key = (
                rel["type"],
                rel["source_id"],
                rel["target_id"],
                rel.get("line"),
                rel.get("metadata", {}).get("route"),
            )
            if key not in seen_rel_keys:
                seen_rel_keys.add(key)
                relationships.append(rel)

        # -------------------------------------------------------------------
        # 1. Structural Relationships: DEFINES & DEFINES_METHOD
        # -------------------------------------------------------------------
        for file_record in files_dict.values():
            file_id = file_record.get("id", "")
            file_path = file_record.get("path", "")
            mod_name = file_record.get("module", "")

            # Module DEFINES top-level functions and classes
            for func in file_record.get("functions", []):
                if not func.get("is_method") and not func.get("parent_function"):
                    func_qualified = (
                        f"{mod_name}.{func['qualified_name']}"
                        if mod_name
                        else func["qualified_name"]
                    )
                    rel_id = _stable_id("rel_defines", file_id, func["id"])
                    add_relationship(
                        {
                            "id": rel_id,
                            "type": "DEFINES",
                            "source_id": file_id,
                            "source_qualified": mod_name,
                            "source_file": file_path,
                            "target_id": func["id"],
                            "target_qualified": func_qualified,
                            "target_file": file_path,
                            "line": func.get("line"),
                            "confidence": "high",
                            "method": "ast_definition",
                            "evidence": f"File defines function '{func['name']}'",
                            "metadata": {"kind": "function"},
                        }
                    )

            for cls in file_record.get("classes", []):
                cls_qualified = (
                    f"{mod_name}.{cls['qualified_name']}"
                    if mod_name
                    else cls["qualified_name"]
                )
                rel_id = _stable_id("rel_defines", file_id, cls["id"])
                add_relationship(
                    {
                        "id": rel_id,
                        "type": "DEFINES",
                        "source_id": file_id,
                        "source_qualified": mod_name,
                        "source_file": file_path,
                        "target_id": cls["id"],
                        "target_qualified": cls_qualified,
                        "target_file": file_path,
                        "line": cls.get("line"),
                        "confidence": "high",
                        "method": "ast_definition",
                        "evidence": f"File defines class '{cls['name']}'",
                        "metadata": {"kind": "class"},
                    }
                )

                # Class DEFINES_METHOD methods
                for method_name in cls.get("methods", []):
                    method_sym = self.index.lookup_in_module(mod_name, method_name)
                    if method_sym is not None:
                        rel_m_id = _stable_id(
                            "rel_defines_method", cls["id"], method_sym["id"]
                        )
                        add_relationship(
                            {
                                "id": rel_m_id,
                                "type": "DEFINES_METHOD",
                                "source_id": cls["id"],
                                "source_qualified": cls_qualified,
                                "source_file": file_path,
                                "target_id": method_sym["id"],
                                "target_qualified": method_sym["qualified_name"],
                                "target_file": file_path,
                                "line": method_sym.get("line"),
                                "confidence": "high",
                                "method": "ast_method",
                                "evidence": f"Class '{cls['name']}' defines method '{method_sym['name']}'",
                                "metadata": {},
                            }
                        )

        # -------------------------------------------------------------------
        # 2. File-level IMPORTS Relationships
        # -------------------------------------------------------------------
        for file_path, file_record in files_dict.items():
            source_file_id = file_record.get("id", "")
            source_mod_name = file_record.get("module", "")

            seen_imported_files: set[str] = set()

            for imp in file_record.get("imports", []):
                line = imp.get("line", 1)
                for alias in imp.get("aliases", []):
                    resolved_import = self.import_resolver.resolve_import_alias(
                        alias, file_record
                    )
                    if (
                        resolved_import
                        and resolved_import.target_file_path
                        and resolved_import.target_file_path != file_path
                    ):
                        target_file_path = resolved_import.target_file_path
                        if target_file_path not in seen_imported_files:
                            seen_imported_files.add(target_file_path)
                            target_mod = self.index.lookup_module_by_path(target_file_path)
                            if target_mod:
                                rel_id = _stable_id(
                                    "rel_imports", source_file_id, target_mod["id"], line
                                )
                                add_relationship(
                                    {
                                        "id": rel_id,
                                        "type": "IMPORTS",
                                        "source_id": source_file_id,
                                        "source_qualified": source_mod_name,
                                        "source_file": file_path,
                                        "target_id": target_mod["id"],
                                        "target_qualified": target_mod["qualified_name"],
                                        "target_file": target_file_path,
                                        "line": line,
                                        "confidence": "high",
                                        "method": "ast_import",
                                        "evidence": f"File imports from '{target_mod['qualified_name']}'",
                                        "metadata": {
                                            "imported_symbol": alias.get("name")
                                        },
                                    }
                                )

        # -------------------------------------------------------------------
        # 3. Class INHERITS Relationships
        # -------------------------------------------------------------------
        for entity in list(entities):
            if entity.get("kind") == "class":
                file_path = entity.get("file_path", "")
                file_record = files_dict.get(file_path, {})
                import_map = self.import_resolver.build_file_import_map(file_record)
                mod_name = file_record.get("module", "")

                for base in entity.get("bases", []):
                    base_entity = None
                    resolved_base = base

                    if "." in base:
                        head, _, attr = base.partition(".")
                        if head in import_map:
                            resolved_base = f"{import_map[head]}.{attr}"
                            base_entity = self.index.lookup_qualified(resolved_base)
                    else:
                        if base in import_map:
                            resolved_base = import_map[base]
                            base_entity = self.index.lookup_qualified(resolved_base)
                        else:
                            base_entity = self.index.lookup_in_module(mod_name, base)
                            if base_entity:
                                resolved_base = base_entity["qualified_name"]

                    if base_entity is not None:
                        rel_id = _stable_id(
                            "rel_inherits", entity["id"], base_entity["id"]
                        )
                        add_relationship(
                            {
                                "id": rel_id,
                                "type": "INHERITS",
                                "source_id": entity["id"],
                                "source_qualified": entity["qualified_name"],
                                "source_file": file_path,
                                "target_id": base_entity["id"],
                                "target_qualified": base_entity["qualified_name"],
                                "target_file": base_entity["file_path"],
                                "line": entity.get("line"),
                                "confidence": "high",
                                "method": "ast_inheritance",
                                "evidence": f"Class inherits from internal class '{base_entity['qualified_name']}'",
                                "metadata": {"external": False, "base_name": base},
                            }
                        )
                    else:
                        # External inheritance (e.g. django.db.models.Model)
                        ext_id = _stable_id("external_class", resolved_base)
                        ext_class_entity = {
                            "id": ext_id,
                            "kind": "class",
                            "name": resolved_base.split(".")[-1],
                            "local_qualified_name": resolved_base.split(".")[-1],
                            "qualified_name": resolved_base,
                            "file_path": "<external>",
                            "line": 1,
                            "is_external": True,
                            "docstring": None,
                        }
                        add_entity(ext_class_entity)

                        rel_id = _stable_id("rel_inherits", entity["id"], ext_id)
                        add_relationship(
                            {
                                "id": rel_id,
                                "type": "INHERITS",
                                "source_id": entity["id"],
                                "source_qualified": entity["qualified_name"],
                                "source_file": file_path,
                                "target_id": ext_id,
                                "target_qualified": resolved_base,
                                "target_file": "<external>",
                                "line": entity.get("line"),
                                "confidence": "high",
                                "method": "external_inheritance",
                                "evidence": f"Class inherits from external class '{resolved_base}'",
                                "metadata": {"external": True, "base_name": base},
                            }
                        )

        # -------------------------------------------------------------------
        # 4. CALLS & INSTANTIATES Relationships
        # -------------------------------------------------------------------
        unresolved_refs: list[dict[str, Any]] = []

        for call in call_results:
            if call.resolved and call.target_entity_id:
                rel_type = (
                    "INSTANTIATES" if call.method == "class_constructor" else "CALLS"
                )
                source_id = call.caller_id
                if not source_id:
                    file_mod = self.index.lookup_module_by_path(call.caller_file)
                    source_id = (
                        file_mod["id"]
                        if file_mod
                        else _stable_id("file", call.caller_file)
                    )

                rel_id = _stable_id(
                    f"rel_{rel_type.lower()}",
                    source_id,
                    call.target_entity_id,
                    call.line,
                    call.column,
                )
                add_relationship(
                    {
                        "id": rel_id,
                        "type": rel_type,
                        "source_id": source_id,
                        "source_qualified": call.caller_qualified or "<module>",
                        "source_file": call.caller_file,
                        "target_id": call.target_entity_id,
                        "target_qualified": call.target_qualified,
                        "target_file": call.target_file,
                        "line": call.line,
                        "confidence": call.confidence,
                        "method": call.method,
                        "evidence": call.reason,
                        "metadata": {
                            "callee_expression": call.callee_expression,
                            "column": call.column,
                        },
                    }
                )
            else:
                ref_id = _stable_id(
                    "unresolved_ref",
                    call.caller_file,
                    call.callee_expression,
                    call.line,
                    call.column,
                )
                unresolved_refs.append(
                    {
                        "id": ref_id,
                        "caller_id": call.caller_id,
                        "caller_qualified": call.caller_qualified,
                        "caller_file": call.caller_file,
                        "expression": call.callee_expression,
                        "line": call.line,
                        "column": call.column,
                        "reason": call.reason,
                        "candidates": call.candidates or [],
                        "status": call.status,
                    }
                )

        # -------------------------------------------------------------------
        # 5. ROUTES_TO & INCLUDES Relationships (Django + FastAPI + Flask)
        # -------------------------------------------------------------------
        for url in url_results:
            source_mod = self.index.lookup_module_by_path(url.source_file)
            source_id = (
                source_mod["id"]
                if source_mod
                else _stable_id("file", url.source_file)
            )

            ev = url.evidence.lower()
            if "fastapi route" in ev:
                route_method = "fastapi_route"
                include_method = "fastapi_include_router"
            elif "flask route" in ev:
                route_method = "flask_route"
                include_method = "flask_register_blueprint"
            elif "fastapi include_router" in ev:
                route_method = "fastapi_route"
                include_method = "fastapi_include_router"
            elif "flask register_blueprint" in ev:
                route_method = "flask_route"
                include_method = "flask_register_blueprint"
            else:
                route_method = "django_url_pattern"
                include_method = "django_include"

            if url.rel_type == "ROUTES_TO" and url.target_entity_id:
                rel_id = _stable_id(
                    "rel_routes_to",
                    source_id,
                    url.target_entity_id,
                    url.route or "",
                    url.line,
                )
                add_relationship(
                    {
                        "id": rel_id,
                        "type": "ROUTES_TO",
                        "source_id": source_id,
                        "source_qualified": url.source_module,
                        "source_file": url.source_file,
                        "target_id": url.target_entity_id,
                        "target_qualified": url.target_qualified,
                        "target_file": url.target_file,
                        "line": url.line,
                        "confidence": url.confidence,
                        "method": route_method,
                        "evidence": url.evidence,
                        "metadata": {
                            "route": url.route,
                            "url_name": url.url_name,
                            "namespace": url.namespace,
                            "view_expression": url.view_expression,
                            "http_methods": _extract_http_methods(url.evidence),
                        },
                    }
                )
            elif url.rel_type == "INCLUDES":
                if url.include_file_id:
                    target_id = url.include_file_id
                else:
                    target_id = _stable_id(
                        "external_include", url.include_target or "unknown"
                    )
                    # Register external module entity
                    ext_mod_name = url.include_target or "unknown"
                    ext_mod_entity = {
                        "id": target_id,
                        "kind": "module",
                        "name": ext_mod_name.split(".")[-1],
                        "local_qualified_name": ext_mod_name,
                        "qualified_name": ext_mod_name,
                        "file_path": "<external>",
                        "line": 1,
                        "is_external": True,
                        "docstring": None,
                    }
                    add_entity(ext_mod_entity)

                rel_id = _stable_id(
                    "rel_includes", source_id, target_id, url.route or "", url.line
                )
                add_relationship(
                    {
                        "id": rel_id,
                        "type": "INCLUDES",
                        "source_id": source_id,
                        "source_qualified": url.source_module,
                        "source_file": url.source_file,
                        "target_id": target_id,
                        "target_qualified": url.include_target,
                        "target_file": url.target_file or "<external>",
                        "line": url.line,
                        "confidence": url.confidence,
                        "method": include_method,
                        "evidence": url.evidence,
                        "metadata": {
                            "route": url.route,
                            "include_target": url.include_target,
                        },
                    }
                )

        # Sort relationships and entities deterministically
        relationships.sort(
            key=lambda r: (
                r["type"],
                r["source_qualified"],
                r["target_qualified"] or "",
                r.get("line") or 0,
            )
        )
        entities.sort(key=lambda e: (e["kind"], e["qualified_name"]))
        unresolved_refs.sort(
            key=lambda u: (
                u["caller_file"],
                u["line"],
                u["column"],
                u["expression"],
            )
        )

        # Validate graph referential integrity
        validation_errors = validate_graph(entities, relationships)

        # Compute stats
        entities_by_kind = dict(Counter(e["kind"] for e in entities))
        rel_by_type = dict(Counter(r["type"] for r in relationships))
        external_count = sum(1 for u in unresolved_refs if u["status"] == "external")
        unresolved_count = sum(
            1
            for u in unresolved_refs
            if u["status"] in ("unresolved", "dynamic", "ambiguous")
        )
        ambiguous_count = sum(1 for u in unresolved_refs if u["status"] == "ambiguous")

        return {
            "repository": {
                "root": str(root) if root else "",
                "files_count": len(files_dict),
            },
            "entities": entities,
            "relationships": relationships,
            "unresolved_references": unresolved_refs,
            "diagnostics": validation_errors,
            "stats": {
                "total_entities": len(entities),
                "entities_by_kind": entities_by_kind,
                "total_relationships": len(relationships),
                "relationships_by_type": rel_by_type,
                "unresolved_calls": unresolved_count,
                "external_calls": external_count,
                "ambiguous_calls": ambiguous_count,
                "validation_errors": len(validation_errors),
            },
        }
