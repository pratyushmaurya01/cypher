"""Repository-wide symbol index built from parsed file records."""

from __future__ import annotations

from typing import Any


class SymbolIndex:
    """Index of all modules, functions, methods, and classes across the repository."""

    def __init__(self, files: list[dict[str, Any]]) -> None:
        self.files = files
        self._by_id: dict[str, dict[str, Any]] = {}
        self._by_qualified: dict[str, dict[str, Any]] = {}
        self._modules: dict[str, dict[str, Any]] = {}
        self._modules_by_path: dict[str, dict[str, Any]] = {}
        self._by_module_and_symbol: dict[str, dict[str, dict[str, Any]]] = {}
        self._globals_by_module: dict[str, dict[str, dict[str, Any]]] = {}
        self._all_entities: list[dict[str, Any]] = []

        self._build_index()

    def _build_index(self) -> None:
        for file_record in self.files:
            file_path = file_record.get("path", "")
            module_name = file_record.get("module", "")
            file_id = file_record.get("id", "")

            # 1. Module entity
            module_entity: dict[str, Any] = {
                "id": file_id,
                "kind": "module",
                "name": module_name.split(".")[-1] if module_name else "",
                "qualified_name": module_name,
                "file_path": file_path,
                "line": 1,
                "is_package": file_record.get("is_package", False),
                "docstring": file_record.get("docstring"),
            }
            self._all_entities.append(module_entity)
            self._by_id[file_id] = module_entity
            self._modules[module_name] = module_entity
            self._modules_by_path[file_path] = module_entity
            if module_name:
                self._by_qualified[module_name] = module_entity

            self._by_module_and_symbol[module_name] = {}
            self._globals_by_module[module_name] = {}

            # 2. Classes
            for cls in file_record.get("classes", []):
                cls_id = cls["id"]
                cls_local = cls["qualified_name"]
                cls_qualified = f"{module_name}.{cls_local}" if module_name else cls_local
                cls_entity: dict[str, Any] = {
                    "id": cls_id,
                    "kind": "class",
                    "name": cls["name"],
                    "local_qualified_name": cls_local,
                    "qualified_name": cls_qualified,
                    "file_path": file_path,
                    "line": cls.get("line", 1),
                    "end_line": cls.get("end_line"),
                    "bases": cls.get("bases", []),
                    "decorators": cls.get("decorators", []),
                    "methods": [
                        f"{module_name}.{m}" if module_name else m
                        for m in cls.get("methods", [])
                    ],
                    "attributes": cls.get("attributes", []),
                    "docstring": cls.get("docstring"),
                }
                self._all_entities.append(cls_entity)
                self._by_id[cls_id] = cls_entity
                self._by_qualified[cls_qualified] = cls_entity
                self._by_module_and_symbol[module_name][cls_local] = cls_entity
                if cls["name"] != cls_local:
                    self._by_module_and_symbol[module_name][cls["name"]] = cls_entity

            # 3. Functions & Methods
            for func in file_record.get("functions", []):
                func_id = func["id"]
                func_local = func["qualified_name"]
                func_qualified = f"{module_name}.{func_local}" if module_name else func_local
                func_entity: dict[str, Any] = {
                    "id": func_id,
                    "kind": "function",
                    "name": func["name"],
                    "local_qualified_name": func_local,
                    "qualified_name": func_qualified,
                    "file_path": file_path,
                    "line": func.get("line", 1),
                    "end_line": func.get("end_line"),
                    "is_method": func.get("is_method", False),
                    "parent_class": func.get("parent_class"),
                    "parent_id": func.get("parent_id"),
                    "decorators": func.get("decorators", []),
                    "arguments": func.get("arguments", []),
                    "return_annotation": func.get("return_annotation"),
                    "docstring": func.get("docstring"),
                }
                self._all_entities.append(func_entity)
                self._by_id[func_id] = func_entity
                self._by_qualified[func_qualified] = func_entity
                self._by_module_and_symbol[module_name][func_local] = func_entity
                if func["name"] != func_local:
                    # e.g., nested functions or methods indexed under bare name if not colliding
                    if func["name"] not in self._by_module_and_symbol[module_name]:
                        self._by_module_and_symbol[module_name][func["name"]] = func_entity

            # 4. Globals
            for glob in file_record.get("globals", []):
                name = glob.get("name")
                if name:
                    self._globals_by_module[module_name][name] = glob

    def lookup_qualified(self, qualified_name: str) -> dict[str, Any] | None:
        """Find entity by full qualified dotted name."""
        return self._by_qualified.get(qualified_name)

    def lookup_module(self, module_name: str) -> dict[str, Any] | None:
        """Find a file/module entity by module dotted name."""
        return self._modules.get(module_name)

    def lookup_module_by_path(self, file_path: str) -> dict[str, Any] | None:
        """Find a file/module entity by relative file path."""
        return self._modules_by_path.get(file_path)

    def lookup_in_module(self, module_name: str, symbol_name: str) -> dict[str, Any] | None:
        """Find a symbol by module dotted name + symbol name."""
        # Check module's symbol table
        mod_symbols = self._by_module_and_symbol.get(module_name)
        if mod_symbols and symbol_name in mod_symbols:
            return mod_symbols[symbol_name]
        # Check full qualified name
        full_name = f"{module_name}.{symbol_name}" if module_name else symbol_name
        return self._by_qualified.get(full_name)

    def lookup_global(self, module_name: str, symbol_name: str) -> dict[str, Any] | None:
        """Find a module global assignment."""
        return self._globals_by_module.get(module_name, {}).get(symbol_name)

    def lookup_by_id(self, entity_id: str) -> dict[str, Any] | None:
        """Find an entity by its stable ID."""
        return self._by_id.get(entity_id)

    def all_entities(self) -> list[dict[str, Any]]:
        """Return all indexed entities."""
        return list(self._all_entities)
