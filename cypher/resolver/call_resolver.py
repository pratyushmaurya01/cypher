"""Resolve function calls to their targets across files with instance method tracking."""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Any

from cypher.resolver.import_resolver import ImportResolver, _COMMON_EXTERNALS
from cypher.resolver.symbol_index import SymbolIndex

_BUILTIN_NAMES = frozenset(dir(builtins))


@dataclass
class ResolvedCall:
    call_id: str
    caller_id: str | None  # function entity ID
    caller_qualified: str | None
    caller_file: str

    callee_expression: str  # original "services.list_users"
    callee_base_name: str  # "list_users"
    callee_receiver: str | None  # "services"

    resolved: bool
    target_entity_id: str | None
    target_qualified: str | None
    target_file: str | None

    confidence: str  # "high" | "low" | "unresolved"
    method: str  # resolution method used
    reason: str  # human readable
    line: int
    column: int
    status: str = "resolved"  # "resolved" | "unresolved" | "external" | "dynamic" | "ambiguous"
    candidates: list[str] | None = None


class CallResolver:
    """Resolves function/method calls to target entities across the codebase."""

    def __init__(self, index: SymbolIndex, import_resolver: ImportResolver) -> None:
        self.index = index
        self.import_resolver = import_resolver

    def resolve_calls(
        self, file_record: dict[str, Any], all_files: dict[str, dict[str, Any]]
    ) -> list[ResolvedCall]:
        """For each call in a file, attempt to resolve the target to an entity."""
        caller_file = file_record.get("path", "")
        caller_module = file_record.get("module", "")
        globals_list = file_record.get("globals", [])

        # Index functions by local qualified name for quick lookup of local assignments
        functions_by_name: dict[str, dict[str, Any]] = {
            func.get("qualified_name", ""): func
            for func in file_record.get("functions", [])
        }

        resolved_calls: list[ResolvedCall] = []

        for call in file_record.get("calls", []):
            call_id = call.get("id", "")
            caller_id = call.get("caller_id")
            caller = call.get("caller")
            caller_class = call.get("caller_class")
            target_kind = call.get("target_kind", "name")
            line = call.get("line", 1)
            column = call.get("column", 0)

            if caller:
                caller_qualified = f"{caller_module}.{caller}" if caller_module else caller
            else:
                caller_qualified = caller_module or None

            callee_expression = call.get("name", "")
            callee_base_name = call.get("base_name", "")
            callee_receiver = call.get("receiver")

            caller_func = functions_by_name.get(caller) if caller else None
            local_assignments = caller_func.get("local_assignments", []) if caller_func else []

            # Use scope-aware import map for this call
            import_map = self.import_resolver.build_scoped_import_map(
                file_record, scope_name=caller, line=line
            )

            result = self._resolve_single_call(
                call_id=call_id,
                caller_id=caller_id,
                caller_qualified=caller_qualified,
                caller_file=caller_file,
                caller_module=caller_module,
                caller_class=caller_class,
                callee_expression=callee_expression,
                callee_base_name=callee_base_name,
                callee_receiver=callee_receiver,
                target_kind=target_kind,
                import_map=import_map,
                local_assignments=local_assignments,
                globals_list=globals_list,
                line=line,
                column=column,
            )
            resolved_calls.append(result)

        return resolved_calls

    def _resolve_single_call(
        self,
        call_id: str,
        caller_id: str | None,
        caller_qualified: str | None,
        caller_file: str,
        caller_module: str,
        caller_class: str | None,
        callee_expression: str,
        callee_base_name: str,
        callee_receiver: str | None,
        target_kind: str,
        import_map: dict[str, str],
        local_assignments: list[dict[str, Any]],
        globals_list: list[dict[str, Any]],
        line: int,
        column: int,
    ) -> ResolvedCall:
        base_kwargs = {
            "call_id": call_id,
            "caller_id": caller_id,
            "caller_qualified": caller_qualified,
            "caller_file": caller_file,
            "callee_expression": callee_expression,
            "callee_base_name": callee_base_name,
            "callee_receiver": callee_receiver,
            "line": line,
            "column": column,
        }

        # -------------------------------------------------------------------
        # Strategy 1: Same-module call
        # -------------------------------------------------------------------
        if callee_receiver is None and callee_base_name:
            candidates = self.index.lookup_in_module_candidates(caller_module, callee_base_name)
            if len(candidates) > 1:
                return ResolvedCall(
                    **base_kwargs,
                    resolved=False,
                    target_entity_id=None,
                    target_qualified=f"{caller_module}.{callee_base_name}",
                    target_file=caller_file,
                    confidence="low",
                    method="same_module",
                    reason=f"Ambiguous same-module call: {len(candidates)} entities found for '{callee_base_name}'",
                    status="ambiguous",
                    candidates=[c["qualified_name"] for c in candidates],
                )
            if candidates:
                same_mod_entity = candidates[0]
                is_class = same_mod_entity.get("kind") == "class"
                method = "class_constructor" if is_class else "same_module"
                return ResolvedCall(
                    **base_kwargs,
                    resolved=True,
                    target_entity_id=same_mod_entity["id"],
                    target_qualified=same_mod_entity["qualified_name"],
                    target_file=same_mod_entity["file_path"],
                    confidence="high",
                    method=method,
                    reason=f"Resolved to same-module {same_mod_entity['kind']} '{same_mod_entity['qualified_name']}'",
                    status="resolved",
                )

        # -------------------------------------------------------------------
        # Strategy 2: Imported symbol call (bare name imported directly)
        # -------------------------------------------------------------------
        if callee_receiver is None and callee_base_name in import_map:
            imported_qualified = import_map[callee_base_name]
            candidates = self.index.lookup_candidates(imported_qualified)
            if len(candidates) > 1:
                # Disambiguate by caller file if possible
                file_candidate = self.index.lookup_qualified_for_file(imported_qualified, caller_file)
                if file_candidate:
                    entity = file_candidate
                else:
                    return ResolvedCall(
                        **base_kwargs,
                        resolved=False,
                        target_entity_id=None,
                        target_qualified=imported_qualified,
                        target_file=None,
                        confidence="low",
                        method="imported_symbol",
                        reason=f"Ambiguous imported symbol call: {len(candidates)} entities found for '{imported_qualified}'",
                        status="ambiguous",
                        candidates=[c["qualified_name"] for c in candidates],
                    )
            elif candidates:
                entity = candidates[0]
            else:
                entity = self.index.lookup_module(imported_qualified)

            if entity is not None:
                is_class = entity.get("kind") == "class"
                method = "class_constructor" if is_class else "imported_symbol"
                return ResolvedCall(
                    **base_kwargs,
                    resolved=True,
                    target_entity_id=entity["id"],
                    target_qualified=entity["qualified_name"],
                    target_file=entity["file_path"],
                    confidence="high",
                    method=method,
                    reason=f"Resolved to imported symbol '{entity['qualified_name']}'",
                    status="resolved",
                )

        # -------------------------------------------------------------------
        # Strategy 3: Self or Cls method call (self.method() or cls.method())
        # -------------------------------------------------------------------
        if callee_receiver in ("self", "cls") and caller_class:
            method_qualified = f"{caller_class}.{callee_base_name}"
            entity = self.index.lookup_in_module(caller_module, method_qualified)
            if entity is not None:
                return ResolvedCall(
                    **base_kwargs,
                    resolved=True,
                    target_entity_id=entity["id"],
                    target_qualified=entity["qualified_name"],
                    target_file=entity["file_path"],
                    confidence="high",
                    method="self_method",
                    reason=f"Resolved to sibling method '{entity['qualified_name']}'",
                    status="resolved",
                )

            # Check inherited methods on base classes
            cls_full = f"{caller_module}.{caller_class}" if caller_module else caller_class
            cls_entity = self.index.lookup_qualified(cls_full)
            if cls_entity:
                inherited = self._find_inherited_method(cls_entity, callee_base_name, import_map)
                if inherited is not None:
                    return ResolvedCall(
                        **base_kwargs,
                        resolved=True,
                        target_entity_id=inherited["id"],
                        target_qualified=inherited["qualified_name"],
                        target_file=inherited["file_path"],
                        confidence="high",
                        method="inherited_method",
                        reason=f"Resolved to inherited method '{inherited['qualified_name']}'",
                        status="resolved",
                    )

        # -------------------------------------------------------------------
        # Strategy 4: Instance Method Call via Local or Global Variable
        # (e.g. service = UserService(); service.get_users())
        # -------------------------------------------------------------------
        if callee_receiver is not None and callee_base_name:
            instance_res = self._resolve_instance_method(
                callee_receiver=callee_receiver,
                callee_base_name=callee_base_name,
                caller_module=caller_module,
                caller_file=caller_file,
                import_map=import_map,
                local_assignments=local_assignments,
                globals_list=globals_list,
                base_kwargs=base_kwargs,
            )
            if instance_res is not None:
                return instance_res

        # -------------------------------------------------------------------
        # Strategy 5: Attribute call via imported module or symbol
        # -------------------------------------------------------------------
        if callee_receiver is not None:
            rec_parts = callee_receiver.split(".")
            rec_head = rec_parts[0]
            rec_tail = rec_parts[1:]

            if rec_head in import_map:
                expanded_head = import_map[rec_head]
                full_receiver = (
                    ".".join([expanded_head] + rec_tail) if rec_tail else expanded_head
                )
                target_qualified = f"{full_receiver}.{callee_base_name}"

                candidates = self.index.lookup_candidates(target_qualified)
                if len(candidates) > 1:
                    return ResolvedCall(
                        **base_kwargs,
                        resolved=False,
                        target_entity_id=None,
                        target_qualified=target_qualified,
                        target_file=None,
                        confidence="low",
                        method="imported_module_attribute",
                        reason=f"Ambiguous attribute call: {len(candidates)} candidates for '{target_qualified}'",
                        status="ambiguous",
                        candidates=[c["qualified_name"] for c in candidates],
                    )
                entity = candidates[0] if candidates else None

                if entity is not None:
                    is_class = entity.get("kind") == "class"
                    method = (
                        "class_constructor" if is_class else "imported_module_attribute"
                    )
                    return ResolvedCall(
                        **base_kwargs,
                        resolved=True,
                        target_entity_id=entity["id"],
                        target_qualified=entity["qualified_name"],
                        target_file=entity["file_path"],
                        confidence="high",
                        method=method,
                        reason=f"Resolved attribute call via imported module to '{entity['qualified_name']}'",
                        status="resolved",
                    )

                # Look up symbol in module if full_receiver is a module
                mod_sym = self.index.lookup_in_module(full_receiver, callee_base_name)
                if mod_sym is not None:
                    is_class = mod_sym.get("kind") == "class"
                    method = (
                        "class_constructor" if is_class else "imported_module_attribute"
                    )
                    return ResolvedCall(
                        **base_kwargs,
                        resolved=True,
                        target_entity_id=mod_sym["id"],
                        target_qualified=mod_sym["qualified_name"],
                        target_file=mod_sym["file_path"],
                        confidence="high",
                        method=method,
                        reason=f"Resolved attribute call in module '{full_receiver}'",
                        status="resolved",
                    )

        # -------------------------------------------------------------------
        # Strategy 6: Class constructor (bare capitalized name in index)
        # -------------------------------------------------------------------
        if callee_receiver is None and callee_base_name and callee_base_name[0].isupper():
            sym = self.index.lookup_in_module(caller_module, callee_base_name)
            if sym is not None and sym.get("kind") == "class":
                return ResolvedCall(
                    **base_kwargs,
                    resolved=True,
                    target_entity_id=sym["id"],
                    target_qualified=sym["qualified_name"],
                    target_file=sym["file_path"],
                    confidence="high",
                    method="class_constructor",
                    reason=f"Instantiates class '{sym['qualified_name']}'",
                    status="resolved",
                )

        # -------------------------------------------------------------------
        # Strategy 7: Built-in or External Package Call
        # -------------------------------------------------------------------
        if callee_receiver is None and callee_base_name in _BUILTIN_NAMES:
            return ResolvedCall(
                **base_kwargs,
                resolved=False,
                target_entity_id=None,
                target_qualified=callee_base_name,
                target_file=None,
                confidence="low",
                method="builtin",
                reason=f"Python built-in function '{callee_base_name}'",
                status="external",
                candidates=[],
            )

        # Check external imports
        target_expr = callee_expression
        head = target_expr.split(".")[0]
        resolved_head = import_map.get(head, head)
        top_pkg = resolved_head.split(".")[0]

        if (head in import_map and self.import_resolver.is_external(top_pkg)) or top_pkg in _COMMON_EXTERNALS:
            expanded_expr = target_expr
            if head in import_map:
                expanded_expr = import_map[head] + target_expr[len(head) :]
            return ResolvedCall(
                **base_kwargs,
                resolved=False,
                target_entity_id=None,
                target_qualified=expanded_expr,
                target_file=None,
                confidence="low",
                method="external",
                reason=f"External package call to '{expanded_expr}'",
                status="external",
                candidates=[],
            )

        # -------------------------------------------------------------------
        # Strategy 8: Dynamic or Unresolvable
        # -------------------------------------------------------------------
        candidates_list: list[str] = []
        if callee_base_name:
            for ent in self.index.all_entities():
                if ent.get("name") == callee_base_name and ent.get("kind") in (
                    "function",
                    "class",
                ):
                    candidates_list.append(ent["qualified_name"])

        status = "dynamic" if target_kind == "dynamic" else "unresolved"
        reason = f"Could not statically resolve '{callee_expression}'"
        if candidates_list:
            reason += f" (found {len(candidates_list)} potential candidates)"

        return ResolvedCall(
            **base_kwargs,
            resolved=False,
            target_entity_id=None,
            target_qualified=None,
            target_file=None,
            confidence="unresolved",
            method="unresolved",
            reason=reason,
            status=status,
            candidates=candidates_list[:5],
        )

    def _resolve_instance_method(
        self,
        callee_receiver: str,
        callee_base_name: str,
        caller_module: str,
        caller_file: str,
        import_map: dict[str, str],
        local_assignments: list[dict[str, Any]],
        globals_list: list[dict[str, Any]],
        base_kwargs: dict[str, Any],
    ) -> ResolvedCall | None:
        """Statically resolves `var.method()` if `var` was instantiated from a class."""
        # Only support simple receivers for variable tracking (e.g. "service", "repo")
        if "." in callee_receiver:
            return None

        constructor_name: str | None = None

        # 1. Check local variable assignments in caller scope
        for assign in reversed(local_assignments):
            if assign.get("target") == callee_receiver:
                constructor_name = assign.get("call_callee") or assign.get("annotation")
                if constructor_name:
                    break

        # 2. Check module globals if not found in local scope
        if not constructor_name:
            for glob in reversed(globals_list):
                if glob.get("name") == callee_receiver:
                    constructor_name = glob.get("call_callee") or glob.get("annotation")
                    if constructor_name:
                        break

        if not constructor_name:
            return None

        # Resolve the constructor class entity
        class_entity = self._resolve_class_symbol(constructor_name, caller_module, import_map)
        if not class_entity or class_entity.get("kind") != "class":
            return None

        # Check if this class defines the method
        method_qualified = f"{class_entity['qualified_name']}.{callee_base_name}"
        method_entity = self.index.lookup_qualified(method_qualified)

        # If not on class directly, check inherited methods
        if method_entity is None:
            method_entity = self._find_inherited_method(
                class_entity, callee_base_name, import_map
            )

        if method_entity is not None:
            return ResolvedCall(
                **base_kwargs,
                resolved=True,
                target_entity_id=method_entity["id"],
                target_qualified=method_entity["qualified_name"],
                target_file=method_entity["file_path"],
                confidence="high",
                method="instance_method",
                reason=f"Resolved instance method call on variable '{callee_receiver}' of class '{class_entity['name']}'",
                status="resolved",
            )

        return None

    def _resolve_class_symbol(
        self, constructor_name: str, caller_module: str, import_map: dict[str, str]
    ) -> dict[str, Any] | None:
        """Resolves a class name (bare or dotted) to a class entity."""
        if "." in constructor_name:
            head, _, tail = constructor_name.partition(".")
            if head in import_map:
                full_name = f"{import_map[head]}.{tail}"
                return self.index.lookup_qualified(full_name)
        else:
            # Check same module
            sym = self.index.lookup_in_module(caller_module, constructor_name)
            if sym is not None and sym.get("kind") == "class":
                return sym
            # Check import map
            if constructor_name in import_map:
                resolved_name = import_map[constructor_name]
                return self.index.lookup_qualified(resolved_name)
        return None

    def _find_inherited_method(
        self,
        class_entity: dict[str, Any],
        method_name: str,
        import_map: dict[str, str],
    ) -> dict[str, Any] | None:
        """Walks base classes to find an inherited method in the repository."""
        file_path = class_entity.get("file_path", "")
        for base in class_entity.get("bases", []):
            base_class_ent: dict[str, Any] | None = None
            if "." in base:
                head, _, attr = base.partition(".")
                if head in import_map:
                    base_class_ent = self.index.lookup_qualified(f"{import_map[head]}.{attr}")
            else:
                if base in import_map:
                    base_class_ent = self.index.lookup_qualified(import_map[base])
                else:
                    mod = class_entity.get("qualified_name", "").rpartition(".")[0]
                    base_class_ent = self.index.lookup_in_module(mod, base)

            if base_class_ent and base_class_ent.get("kind") == "class":
                target_method_name = f"{base_class_ent['qualified_name']}.{method_name}"
                found = self.index.lookup_qualified(target_method_name)
                if found:
                    return found
                # Recurse
                rec = self._find_inherited_method(base_class_ent, method_name, import_map)
                if rec:
                    return rec
        return None
