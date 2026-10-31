"""Resolve function calls to their targets across files."""

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
        import_map = self.import_resolver.build_file_import_map(file_record)

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

            # Try resolution strategies in sequence
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
            same_mod_entity = self.index.lookup_in_module(caller_module, callee_base_name)
            if same_mod_entity is not None:
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
            entity = self.index.lookup_qualified(imported_qualified)
            if entity is None:
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
        # Strategy 3: Attribute call via imported module or symbol
        # -------------------------------------------------------------------
        if callee_receiver is not None:
            # Check receiver head in import_map
            rec_parts = callee_receiver.split(".")
            rec_head = rec_parts[0]
            rec_tail = rec_parts[1:]

            if rec_head in import_map:
                expanded_head = import_map[rec_head]
                full_receiver = ".".join([expanded_head] + rec_tail) if rec_tail else expanded_head
                target_qualified = f"{full_receiver}.{callee_base_name}"

                entity = self.index.lookup_qualified(target_qualified)
                if entity is not None:
                    is_class = entity.get("kind") == "class"
                    method = "class_constructor" if is_class else "imported_module_attribute"
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
                    method = "class_constructor" if is_class else "imported_module_attribute"
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
        # Strategy 4: Self method call (self.method_name(...))
        # -------------------------------------------------------------------
        if callee_receiver == "self" and caller_class:
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

        # -------------------------------------------------------------------
        # Strategy 5: Class constructor (bare capitalized name in index)
        # -------------------------------------------------------------------
        if callee_receiver is None and callee_base_name and callee_base_name[0].isupper():
            # Check same module or any indexed class with this name
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
        # Strategy 6: Check for External Packages or Built-ins
        # -------------------------------------------------------------------
        # Check builtins
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

        if top_pkg in _COMMON_EXTERNALS:
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
        # Strategy 7: Dynamic or Unresolvable
        # -------------------------------------------------------------------
        # Collect possible candidates with matching base name
        candidates: list[str] = []
        if callee_base_name:
            for ent in self.index.all_entities():
                if ent.get("name") == callee_base_name and ent.get("kind") in ("function", "class"):
                    candidates.append(ent["qualified_name"])

        status = "dynamic" if target_kind == "dynamic" else "unresolved"
        reason = f"Could not statically resolve '{callee_expression}'"
        if candidates:
            reason += f" (found {len(candidates)} potential candidates)"

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
            candidates=candidates[:5],
        )
