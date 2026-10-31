"""Resolve imports across files using the SymbolIndex with scope awareness."""

from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any

from cypher.resolver.symbol_index import SymbolIndex

# Built-in stdlib module names available in Python 3.10+
_STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ()))

# Widely used third-party packages to recognize as external dependencies
_COMMON_EXTERNALS = frozenset(
    {
        "django",
        "flask",
        "fastapi",
        "starlette",
        "celery",
        "click",
        "typer",
        "pytest",
        "requests",
        "urllib",
        "urllib3",
        "httpx",
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
        "pydantic_core",
        "sqlalchemy",
        "alembic",
        "dotenv",
        "jwt",
        "redis",
        "boto3",
        "botocore",
        "numpy",
        "pandas",
        "scipy",
        "yaml",
        "toml",
        "tomllib",
        "logging",
        "traceback",
        "inspect",
        "shutil",
        "tempfile",
        "glob",
        "subprocess",
        "io",
        "uuid",
    }
) | _STDLIB_MODULES


@dataclass
class ResolvedImport:
    local_name: str
    qualified_name: str  # what the alias resolves to
    target_entity_id: str | None  # entity ID if found in index
    target_entity_kind: str | None  # "module" | "function" | "class" | "external"
    target_file_path: str | None
    confidence: str  # "high" | "low" | "unresolved"
    reason: str
    is_external: bool = False
    status: str = "resolved"  # "resolved" | "external" | "unresolved"


class ImportResolver:
    """Resolves import aliases to concrete entities across the repository."""

    def __init__(self, index: SymbolIndex) -> None:
        self.index = index
        # Identify top-level package names that belong to the scanned repository
        self._repo_root_packages: set[str] = set()
        for mod in self.index._modules.keys():
            if mod:
                self._repo_root_packages.add(mod.split(".")[0])

    def resolve_import_alias(
        self, alias: dict[str, Any], importing_file: dict[str, Any]
    ) -> ResolvedImport | None:
        """Given one alias record from a file's imports, resolve it to an entity."""
        local_name = alias.get("local_name")
        if not local_name:
            return None

        qualified_name = alias.get("qualified_name") or alias.get("name") or ""
        resolved_module = alias.get("resolved_module")
        top_pkg = qualified_name.split(".")[0] if qualified_name else ""

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
                is_external=False,
                status="resolved",
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
                is_external=False,
                status="resolved",
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
                        is_external=False,
                        status="resolved",
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
                        is_external=False,
                        status="resolved",
                    )
                # If resolved_module is internal to the repo, but symbol was not found
                mod_internal = self.index.lookup_module(resolved_module)
                if mod_internal is not None:
                    return ResolvedImport(
                        local_name=local_name,
                        qualified_name=f"{resolved_module}.{symbol_name}",
                        target_entity_id=None,
                        target_entity_kind=None,
                        target_file_path=mod_internal["file_path"],
                        confidence="unresolved",
                        reason=f"Symbol '{symbol_name}' not found in internal module '{resolved_module}'",
                        is_external=False,
                        status="unresolved",
                    )

        # 4. Check if external package or stdlib (relative imports are never external)
        is_relative = alias.get("is_relative", False)
        if not is_relative and (
            top_pkg in _COMMON_EXTERNALS or (top_pkg and top_pkg not in self._repo_root_packages)
        ):
            return ResolvedImport(
                local_name=local_name,
                qualified_name=qualified_name,
                target_entity_id=None,
                target_entity_kind="external",
                target_file_path=None,
                confidence="high",
                reason=f"External dependency ({top_pkg})",
                is_external=True,
                status="external",
            )

        # 5. Truly Unresolved internal import
        return ResolvedImport(
            local_name=local_name,
            qualified_name=qualified_name,
            target_entity_id=None,
            target_entity_kind=None,
            target_file_path=None,
            confidence="unresolved",
            reason=f"Could not resolve '{qualified_name}' in repository index",
            is_external=False,
            status="unresolved",
        )

    def is_external(self, name: str) -> bool:
        """Return True if the top-level identifier represents an external library or stdlib."""
        top = name.split(".")[0] if name else ""
        return top in _COMMON_EXTERNALS or (bool(top) and top not in self._repo_root_packages)

    def build_file_import_map(self, file_record: dict[str, Any]) -> dict[str, str]:
        """Returns {local_name → qualified_name} for module-level imports in a file."""
        return self.build_scoped_import_map(file_record, scope_name=None)

    def build_scoped_import_map(
        self,
        file_record: dict[str, Any],
        scope_name: str | None = None,
        line: int | None = None,
    ) -> dict[str, str]:
        """Returns {local_name → qualified_name} considering lexical scope and line order.

        Module-level imports are loaded first. If a `scope_name` is provided (e.g. function or class),
        imports declared specifically within that scope are layered on top.
        """
        module_imports: dict[str, str] = {}
        scoped_imports: dict[str, str] = {}

        for imp in file_record.get("imports", []):
            imp_mod = imp.get("module")
            imp_scope = imp.get("scope", "module")
            imp_scope_name = imp.get("scope_name")
            imp_line = imp.get("line", 1)

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

                if not qualified:
                    continue

                if imp_scope == "module":
                    module_imports[local_name] = qualified
                elif scope_name is not None and (
                    imp_scope_name == scope_name or imp_scope_name is None
                ):
                    # Check line constraint if specified
                    if line is None or imp_line <= line:
                        scoped_imports[local_name] = qualified

        # Scoped imports shadow module imports
        combined = dict(module_imports)
        combined.update(scoped_imports)
        return combined
