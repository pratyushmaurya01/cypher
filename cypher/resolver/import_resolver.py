"""Resolve imports across files using the SymbolIndex."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cypher.resolver.symbol_index import SymbolIndex

# Known external top-level packages to classify quickly
_COMMON_EXTERNALS = frozenset(
    {
        "django",
        "flask",
        "fastapi",
        "celery",
        "click",
        "typer",
        "pytest",
        "requests",
        "urllib",
        "os",
        "sys",
        "pathlib",
        "typing",
        "collections",
        "datetime",
        "time",
        "json",
        "re",
        "math",
        "hashlib",
        "functools",
        "itertools",
        "contextlib",
        "dataclasses",
        "unittest",
        "abc",
        "pydantic",
        "sqlalchemy",
        "alembic",
    }
)


@dataclass
class ResolvedImport:
    local_name: str
    qualified_name: str  # what the alias resolves to
    target_entity_id: str | None  # entity ID if found in index
    target_entity_kind: str | None  # "module" | "function" | "class"
    target_file_path: str | None
    confidence: str  # "high" | "low" | "unresolved"
    reason: str


class ImportResolver:
    """Resolves import aliases to concrete entities across the repository."""

    def __init__(self, index: SymbolIndex) -> None:
        self.index = index

    def resolve_import_alias(
        self, alias: dict[str, Any], importing_file: dict[str, Any]
    ) -> ResolvedImport | None:
        """Given one alias record from a file's imports, resolve it to an entity."""
        local_name = alias.get("local_name")
        if not local_name:
            return None

        qualified_name = alias.get("qualified_name") or alias.get("name") or ""
        resolved_module = alias.get("resolved_module")

        # 1. Look up exact qualified name in symbol index (function or class or module)
        entity = self.index.lookup_qualified(qualified_name)
        if entity is not None:
            return ResolvedImport(
                local_name=local_name,
                qualified_name=qualified_name,
                target_entity_id=entity["id"],
                target_entity_kind=entity["kind"],
                target_file_path=entity["file_path"],
                confidence="high",
                reason=f"Resolved to internal {entity['kind']} '{qualified_name}'",
            )

        # 2. Check if qualified_name is an indexed module
        mod = self.index.lookup_module(qualified_name)
        if mod is not None:
            return ResolvedImport(
                local_name=local_name,
                qualified_name=qualified_name,
                target_entity_id=mod["id"],
                target_entity_kind="module",
                target_file_path=mod["file_path"],
                confidence="high",
                reason=f"Resolved to internal module '{qualified_name}'",
            )

        # 3. If imported from a module, check if the symbol is in that module
        if resolved_module:
            symbol_name = alias.get("name")
            if symbol_name and symbol_name != "*":
                sym = self.index.lookup_in_module(resolved_module, symbol_name)
                if sym is not None:
                    return ResolvedImport(
                        local_name=local_name,
                        qualified_name=sym["qualified_name"],
                        target_entity_id=sym["id"],
                        target_entity_kind=sym["kind"],
                        target_file_path=sym["file_path"],
                        confidence="high",
                        reason=f"Resolved symbol in module '{resolved_module}'",
                    )
                # Check globals in that module (e.g. User = get_user_model())
                glob = self.index.lookup_global(resolved_module, symbol_name)
                if glob is not None:
                    mod_parent = self.index.lookup_module(resolved_module)
                    return ResolvedImport(
                        local_name=local_name,
                        qualified_name=f"{resolved_module}.{symbol_name}",
                        target_entity_id=mod_parent["id"] if mod_parent else None,
                        target_entity_kind="module",
                        target_file_path=mod_parent["file_path"] if mod_parent else None,
                        confidence="high",
                        reason=f"Resolved to global variable in module '{resolved_module}'",
                    )

        # 4. Check if external package
        top_pkg = qualified_name.split(".")[0] if qualified_name else ""
        if top_pkg in _COMMON_EXTERNALS:
            return ResolvedImport(
                local_name=local_name,
                qualified_name=qualified_name,
                target_entity_id=None,
                target_entity_kind=None,
                target_file_path=None,
                confidence="high",
                reason=f"External dependency ({top_pkg})",
            )

        # 5. Unresolved
        return ResolvedImport(
            local_name=local_name,
            qualified_name=qualified_name,
            target_entity_id=None,
            target_entity_kind=None,
            target_file_path=None,
            confidence="unresolved",
            reason=f"Could not resolve '{qualified_name}' in repository index",
        )

    def build_file_import_map(self, file_record: dict[str, Any]) -> dict[str, str]:
        """Returns {local_name → qualified_name} for all imports in a file."""
        import_map: dict[str, str] = {}
        for imp in file_record.get("imports", []):
            imp_mod = imp.get("module")
            for alias in imp.get("aliases", []):
                local_name = alias.get("local_name")
                if not local_name:
                    continue
                qualified = alias.get("qualified_name")
                if not qualified and alias.get("resolved_module"):
                    qualified = f"{alias['resolved_module']}.{alias['name']}"
                if not qualified and imp_mod and alias.get("name"):
                    qualified = f"{imp_mod}.{alias['name']}"
                if not qualified:
                    qualified = alias.get("name")
                if qualified:
                    import_map[local_name] = qualified
        return import_map
