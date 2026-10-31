"""Static Python repository parser for Cypher.

``parse_repository`` returns JSON-serializable records suitable for later graph
construction. Its top-level shape is ``root``, ``files``, ``errors``, and
``stats``. Each file contains imports, functions, classes, calls, module-level
assignments, and heuristic framework hints. All cross-file names are raw
references: this module never imports or executes scanned code.

Output schema (additions over the original contract are marked NEW)
-------------------------------------------------------------------
stats
    ``scanned_files`` = ``parsed_files`` + ``failed_files`` (files that were
    actually read/attempted). ``skipped_files`` is separate: ignored
    directories, symlinked files, non-regular files and oversized files.
    Files that were parsed with only a *warning* (e.g. fallback decoding) count
    as parsed.

errors
    One record per problem: ``path``, ``error_type``, ``message`` and
    optionally ``line``/``column`` (original), plus NEW ``severity``
    (``"error"`` = the file was not analysed, ``"warning"`` = the file was
    skipped or analysed with caveats) and NEW ``stage`` (``"discovery"``,
    ``"read"``, ``"decode"``, ``"parse"`` or ``"analyze"``).

file
    Original keys: ``id``, ``path``, ``module``, ``is_package``, ``line_count``,
    ``sha256``, ``docstring``, ``imports``, ``functions``, ``classes``,
    ``calls``, ``globals``, ``framework_hints``. NEW: ``encoding`` (codec used)
    and ``decode_fallback`` (True when replacement-character decoding was used).

imports (one record per statement; names grouped under ``aliases``)
    ``kind`` ("import" | "from"), ``module`` (as written, ``None`` for
    ``from . import x``), ``level``, ``line``, ``conditional``,
    ``type_checking``, NEW ``scope`` ("module" | "class" | "function"), and
    ``aliases``: one entry per imported name::

        name             original imported name ("a.b" for ``import a.b``,
                         the symbol for ``from m import symbol``, "*" for star)
        alias            the ``as`` name, or None
        local_name       the name bound in the importing namespace (None for
                         star imports; first segment for ``import a.b``)
        resolved_module  absolute dotted module the name comes from; for
                         relative imports it is resolved against this file's
                         package, or None when the import climbs above the
                         top-level package of the scanned tree
        qualified_name   absolute dotted path of the imported object
                         (``resolved_module`` + "." + ``name`` for from-imports;
                         it may be a symbol *or* a submodule - static analysis
                         cannot tell). None for star/unresolvable imports.

functions / classes
    Original keys are preserved. NEW: ``parent_id``, ``is_method`` (functions),
    ``method_ids`` / ``nested_class_ids`` (classes). ``methods`` lists only
    functions defined directly in the class body.

calls
    Original keys ``id``, ``name``, ``base_name``, ``receiver``, ``line``,
    ``column``, ``caller`` are preserved; ``caller`` is the qualified name of
    the function/lambda *executing* the call, or None. NEW:

    ``caller_type``   "module" | "class" | "function" (where the call executes)
    ``caller_id``     id of the executing function/class record (None: module)
    ``caller_class``  qualified name of the nearest lexically enclosing class
    ``context``       "body" | "decorator" | "default_argument" | "annotation" |
                      "class_base"; decorators, defaults, annotations and class
                      bases execute in the *surrounding* scope, so they are
                      attributed to it rather than to the definition they
                      belong to
    ``target_kind``   "name" | "attribute" | "dynamic"

framework_hints
    ``framework``, ``kind``, ``name``, ``line`` (original) plus NEW
    ``confidence`` ("high": evidence observed through imports/assignments in
    this file; "low": name-based or partial evidence only), ``evidence`` (what
    was observed) and optionally ``details`` (literal route paths etc.).

Configuration
-------------
Maximum file size in bytes: ``parse_repository(max_file_size=...)`` >
environment variable ``CYPHER_MAX_FILE_SIZE`` > ``DEFAULT_MAX_FILE_SIZE``.
"""

from __future__ import annotations

import ast
import hashlib
import io
import logging
import os
import stat
import tokenize
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, NamedTuple

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_IGNORED_DIRECTORIES",
    "DEFAULT_MAX_FILE_SIZE",
    "MAX_FILE_SIZE_ENV_VAR",
    "parse_repository",
]

DEFAULT_MAX_FILE_SIZE = 1_000_000
MAX_FILE_SIZE_ENV_VAR = "CYPHER_MAX_FILE_SIZE"
DEFAULT_IGNORED_DIRECTORIES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "virtualenv",
        "__pycache__",
        "node_modules",
        "build",
        "dist",
    }
)

_FALLBACK_ENCODING = "utf-8-sig"
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "trace"})
_FASTAPI_ATTRS = _HTTP_METHODS | {"api_route", "websocket"}
_FLASK_ATTRS = _HTTP_METHODS | {"route"}
_FASTAPI_APPS = frozenset({"fastapi.FastAPI", "fastapi.APIRouter"})
_FLASK_APPS = frozenset({"flask.Flask", "flask.Blueprint"})
_CLICK_DECORATORS = frozenset({"click.command", "click.group"})
_FIXTURE_DECORATORS = frozenset({"pytest.fixture", "pytest_asyncio.fixture"})
_URL_FUNCTIONS = frozenset({"path", "re_path", "include"})


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _stable_id(kind: str, *parts: object) -> str:
    value = "\0".join((kind, *(str(part) for part in parts)))
    return f"{kind}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


def _module_name(relative_path: Path) -> tuple[str, bool]:
    is_package = relative_path.name == "__init__.py"
    parts = relative_path.with_suffix("").parts
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _expression(node: ast.AST | None, fallback: str = "<unknown>") -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (AttributeError, RecursionError, ValueError):
        return fallback


def _target_names(target: ast.AST) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_target_names(element))
        return names
    return []


def _literal_representation(node: ast.AST, limit: int = 200) -> str:
    # MemoryError is deliberately not caught: it must not be silently swallowed.
    try:
        representation = repr(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, OverflowError, RecursionError):
        representation = "<non-literal>"
    if len(representation) > limit:
        return representation[: limit - 3] + "..."
    return representation


def _type_checking_polarity(node: ast.AST) -> bool | None:
    """Classify an ``if`` test.

    ``True``: the *body* only runs for type checkers (``if TYPE_CHECKING``).
    ``False``: the *else* branch does (``if not TYPE_CHECKING``).
    ``None``: the test is unrelated or too complex to classify.
    """
    if isinstance(node, ast.Name):
        return True if node.id == "TYPE_CHECKING" else None
    if isinstance(node, ast.Attribute):
        return True if node.attr == "TYPE_CHECKING" else None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _type_checking_polarity(node.operand)
        return None if inner is None else not inner
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        if any(_type_checking_polarity(value) is True for value in node.values):
            return True
    return None


def _is_generator(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    class YieldFinder(ast.NodeVisitor):
        found = False

        def visit_Yield(self, item: ast.Yield) -> None:
            self.found = True

        def visit_YieldFrom(self, item: ast.YieldFrom) -> None:
            self.found = True

        def visit_FunctionDef(self, item: ast.FunctionDef) -> None:
            return  # nested functions have their own generator status

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, item: ast.Lambda) -> None:
            return

        def visit_ClassDef(self, item: ast.ClassDef) -> None:
            return

    finder = YieldFinder()
    for statement in node.body:
        finder.visit(statement)
    return finder.found


def _qualified_expression_name(node: ast.AST) -> tuple[str, str, str | None]:
    if isinstance(node, ast.Name):
        return node.id, node.id, None
    if isinstance(node, ast.Attribute):
        receiver = _expression(node.value, "<dynamic>")
        name = _expression(node, "<dynamic>")
        return name, node.attr, receiver
    return _expression(node, "<dynamic>"), "<dynamic>", None


def _resolve_import_module(
    module: str,
    is_package: bool,
    level: int,
    imported_module: str | None,
) -> str | None:
    """Return the absolute module a ``from`` import reads from.

    Relative imports are resolved against ``module`` assuming the scanned root
    is on ``sys.path``. ``None`` means the import climbs above the top-level
    package of the scanned tree and cannot be resolved statically.
    """
    if level == 0:
        return imported_module or None
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    ascent = level - 1
    if ascent >= len(package_parts):
        return None
    base = package_parts[: len(package_parts) - ascent]
    if imported_module:
        base = base + imported_module.split(".")
    return ".".join(base)


def _decorator_info(decorator: ast.expr) -> dict[str, Any]:
    """Extract structured, literal-only facts from a decorator expression."""
    call = decorator if isinstance(decorator, ast.Call) else None
    target = call.func if call is not None else decorator
    path: str | None = None
    methods: list[str] | None = None
    if call is not None:
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            path = call.args[0].value
        for keyword in call.keywords:
            if keyword.arg == "methods":
                try:
                    value = ast.literal_eval(keyword.value)
                except (ValueError, TypeError, SyntaxError, OverflowError, RecursionError):
                    continue
                if isinstance(value, (list, tuple, set)) and all(isinstance(v, str) for v in value):
                    methods = sorted(v.upper() for v in value)
    return {"callee": _expression(target), "path": path, "methods": methods}


class _ImportTable:
    """Maps local names to absolute dotted origins using a file's own imports."""

    def __init__(self, imports: list[dict[str, Any]]) -> None:
        self._bindings: dict[str, str] = {}
        self._modules: set[str] = set()
        for record in imports:
            for alias in record["aliases"]:
                if record["kind"] == "import":
                    if alias["alias"]:
                        self._bindings[alias["alias"]] = alias["name"]
                    else:
                        top = alias["name"].split(".")[0]
                        self._bindings[top] = top
                    self._modules.add(alias["name"])
                else:
                    if alias["resolved_module"]:
                        self._modules.add(alias["resolved_module"])
                    if alias["local_name"] and alias["qualified_name"]:
                        self._bindings[alias["local_name"]] = alias["qualified_name"]

    def resolve(self, dotted: str) -> str | None:
        """Expand the first segment through the imports; None if it is not imported."""
        head, _, tail = dotted.partition(".")
        origin = self._bindings.get(head)
        if origin is None:
            return None
        return f"{origin}.{tail}" if tail else origin

    def imports_package(self, package: str) -> bool:
        prefix = package + "."
        return any(m == package or m.startswith(prefix) for m in self._modules)


@dataclass
class _Scope:
    """One lexical scope on the visitor's stack."""

    kind: str  # "module" | "class" | "function"
    qualified_name: str | None = None
    record: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# AST visitor
# --------------------------------------------------------------------------- #


class _SourceVisitor(ast.NodeVisitor):
    """Collects the records for a single module. Call ``finalize`` after ``visit``."""

    def __init__(self, path: str, module: str, is_package: bool) -> None:
        self.path = path
        self.module = module
        self.is_package = is_package
        self.imports: list[dict[str, Any]] = []
        self.functions: list[dict[str, Any]] = []
        self.classes: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.globals: list[dict[str, Any]] = []
        self.framework_hints: list[dict[str, Any]] = []
        self.scopes: list[_Scope] = [_Scope("module")]
        self.conditional_depth = 0
        self.type_checking_depth = 0
        self._context = "body"
        self._occurrences: dict[tuple[str, str], int] = {}
        self._lambda_occurrences: dict[str, int] = {}
        self._definitions: list[dict[str, Any]] = []
        self._call_assignments: dict[str, str] = {}
        self._urlpatterns: list[tuple[int, ast.expr | None]] = []

    # -- scope helpers ------------------------------------------------------

    @property
    def _scope(self) -> _Scope:
        return self.scopes[-1]

    def _nearest(self, kind: str) -> _Scope | None:
        for scope in reversed(self.scopes):
            if scope.kind == kind:
                return scope
        return None

    def _qualify(self, name: str) -> str:
        parent = self._scope.qualified_name
        return f"{parent}.{name}" if parent else name

    def _id(self, kind: str, qualified_name: str) -> str:
        key = (kind, qualified_name)
        occurrence = self._occurrences.get(key, 0)
        self._occurrences[key] = occurrence + 1
        return _stable_id(kind, self.path, qualified_name, occurrence)

    @contextmanager
    def _context_label(self, label: str) -> Iterator[None]:
        previous = self._context
        self._context = label
        try:
            yield
        finally:
            self._context = previous

    def _branch(self, statements: list[ast.stmt], type_checking: bool = False) -> None:
        self.conditional_depth += 1
        self.type_checking_depth += int(type_checking)
        for statement in statements:
            self.visit(statement)
        self.conditional_depth -= 1
        self.type_checking_depth -= int(type_checking)

    # -- imports ------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        aliases = [
            {
                "name": alias.name,
                "alias": alias.asname,
                "local_name": alias.asname or alias.name.split(".")[0],
                "resolved_module": alias.name,
                "qualified_name": alias.name,
            }
            for alias in node.names
        ]
        self._add_import(node, "import", None, 0, aliases)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        resolved = _resolve_import_module(self.module, self.is_package, node.level, node.module)
        aliases = []
        for alias in node.names:
            is_star = alias.name == "*"
            aliases.append(
                {
                    "name": alias.name,
                    "alias": alias.asname,
                    "local_name": None if is_star else (alias.asname or alias.name),
                    "resolved_module": resolved,
                    "qualified_name": (
                        None if is_star or resolved is None else f"{resolved}.{alias.name}"
                    ),
                }
            )
        self._add_import(node, "from", node.module, node.level, aliases)

    def _add_import(
        self,
        node: ast.Import | ast.ImportFrom,
        kind: str,
        source_module: str | None,
        level: int,
        aliases: list[dict[str, Any]],
    ) -> None:
        self.imports.append(
            {
                "kind": kind,
                "module": source_module,
                "level": level,
                "aliases": aliases,
                "line": node.lineno,
                "conditional": self.conditional_depth > 0,
                "type_checking": self.type_checking_depth > 0,
                "scope": self._scope.kind,
            }
        )

    # -- control flow -------------------------------------------------------

    def visit_If(self, node: ast.If) -> None:
        polarity = _type_checking_polarity(node.test)
        self.visit(node.test)
        self._branch(node.body, type_checking=polarity is True)
        if node.orelse:
            self._branch(node.orelse, type_checking=polarity is False)

    def visit_Try(self, node: ast.Try) -> None:
        self._branch(node.body)
        for handler in node.handlers:
            self.conditional_depth += 1
            self.visit(handler)
            self.conditional_depth -= 1
        for statement in node.orelse + node.finalbody:
            self.visit(statement)

    visit_TryStar = visit_Try

    # -- calls --------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        call_name, base_name, receiver = _qualified_expression_name(node.func)
        scope = self._scope
        caller: str | None = None
        caller_id: str | None = None
        caller_key = "<module>"
        if scope.kind == "function" and scope.record is not None:
            caller = scope.qualified_name
            caller_id = scope.record["id"]
            caller_key = caller or "<module>"
        elif scope.kind == "class" and scope.record is not None:
            caller_id = scope.record["id"]
            caller_key = f"class:{scope.qualified_name}"
        enclosing_class = self._nearest("class")
        if isinstance(node.func, ast.Name):
            target_kind = "name"
        elif isinstance(node.func, ast.Attribute):
            target_kind = "attribute"
        else:
            target_kind = "dynamic"
        self.calls.append(
            {
                "id": self._id("call", f"{caller_key}:{call_name}"),
                "name": call_name,
                "base_name": base_name,
                "receiver": receiver,
                "line": node.lineno,
                "column": node.col_offset,
                "caller": caller,
                "caller_type": scope.kind,
                "caller_id": caller_id,
                "caller_class": enclosing_class.qualified_name if enclosing_class else None,
                "context": self._context,
                "target_kind": target_kind,
            }
        )
        self.generic_visit(node)

    # -- functions ----------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def _visit_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        # Decorators, defaults and annotations run in the *enclosing* scope.
        with self._context_label("decorator"):
            for decorator in node.decorator_list:
                self.visit(decorator)
        with self._context_label("default_argument"):
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                self.visit(default)
        with self._context_label("annotation"):
            if node.returns:
                self.visit(node.returns)
            all_arguments = (
                node.args.posonlyargs
                + node.args.args
                + node.args.kwonlyargs
                + [a for a in (node.args.vararg, node.args.kwarg) if a is not None]
            )
            for argument in all_arguments:
                if argument.annotation:
                    self.visit(argument.annotation)

        parent_scope = self._scope
        qualified_name = self._qualify(node.name)
        function_id = self._id("function", qualified_name)
        parent_function = self._nearest("function")
        parent_class = self._nearest("class")
        record = {
            "id": function_id,
            "name": node.name,
            "qualified_name": qualified_name,
            "kind": "async_function" if is_async else "function",
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "parent": parent_scope.qualified_name,
            "parent_function": parent_function.qualified_name if parent_function else None,
            "parent_class": parent_class.qualified_name if parent_class else None,
            "arguments": self._arguments(node.args),
            "return_annotation": _expression(node.returns),
            "decorators": [_expression(item) for item in node.decorator_list],
            "docstring": ast.get_docstring(node),
            "is_generator": _is_generator(node),
            "parent_id": parent_scope.record["id"] if parent_scope.record else None,
            "is_method": parent_scope.kind == "class",
        }
        self.functions.append(record)
        if parent_scope.kind == "class" and parent_scope.record is not None:
            parent_scope.record["methods"].append(qualified_name)
            parent_scope.record["method_ids"].append(function_id)
        self._definitions.append(
            {
                "kind": "function",
                "name": qualified_name,
                "node_name": node.name,
                "line": node.lineno,
                "decorators": [_decorator_info(item) for item in node.decorator_list],
            }
        )

        self.scopes.append(_Scope("function", qualified_name, record))
        with self._context_label("body"):
            for statement in node.body:
                self.visit(statement)
        self.scopes.pop()

    def _arguments(self, arguments: ast.arguments) -> list[dict[str, Any]]:
        positional = arguments.posonlyargs + arguments.args
        positional_defaults: list[ast.expr | None] = [None] * (
            len(positional) - len(arguments.defaults)
        ) + list(arguments.defaults)
        result: list[dict[str, Any]] = []
        for index, argument in enumerate(arguments.posonlyargs):
            result.append(self._argument(argument, "positional_only", positional_defaults[index]))
        for index, argument in enumerate(arguments.args, start=len(arguments.posonlyargs)):
            result.append(self._argument(argument, "positional", positional_defaults[index]))
        if arguments.vararg:
            result.append(self._argument(arguments.vararg, "var_positional", None))
        for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
            result.append(self._argument(argument, "keyword_only", default))
        if arguments.kwarg:
            result.append(self._argument(arguments.kwarg, "var_keyword", None))
        return result

    @staticmethod
    def _argument(argument: ast.arg, kind: str, default: ast.expr | None) -> dict[str, Any]:
        return {
            "name": argument.arg,
            "kind": kind,
            "annotation": _expression(argument.annotation),
            "default": _expression(default) if default is not None else None,
        }

    def visit_Lambda(self, node: ast.Lambda) -> None:
        with self._context_label("default_argument"):
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
                self.visit(default)
        parent_scope = self._scope
        prefix = parent_scope.qualified_name or ""
        occurrence = self._lambda_occurrences.get(prefix, 0) + 1
        self._lambda_occurrences[prefix] = occurrence
        qualified_name = self._qualify(f"<lambda:{occurrence}>")
        parent_function = self._nearest("function")
        parent_class = self._nearest("class")
        record = {
            "id": self._id("function", qualified_name),
            "name": "<lambda>",
            "qualified_name": qualified_name,
            "kind": "lambda",
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "parent": parent_scope.qualified_name,
            "parent_function": parent_function.qualified_name if parent_function else None,
            "parent_class": parent_class.qualified_name if parent_class else None,
            "arguments": self._arguments(node.args),
            "return_annotation": "",
            "decorators": [],
            "docstring": None,
            "is_generator": False,
            "parent_id": parent_scope.record["id"] if parent_scope.record else None,
            "is_method": False,
        }
        self.functions.append(record)
        self.scopes.append(_Scope("function", qualified_name, record))
        with self._context_label("body"):
            self.visit(node.body)
        self.scopes.pop()

    # -- classes ------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        with self._context_label("decorator"):
            for decorator in node.decorator_list:
                self.visit(decorator)
        with self._context_label("class_base"):
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)

        parent_scope = self._scope
        qualified_name = self._qualify(node.name)
        class_id = self._id("class", qualified_name)
        parent_function = self._nearest("function")
        parent_class = self._nearest("class")
        bases = [_expression(base) for base in node.bases]
        record = {
            "id": class_id,
            "name": node.name,
            "qualified_name": qualified_name,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", node.lineno),
            "parent_class": parent_class.qualified_name if parent_class else None,
            "parent_function": parent_function.qualified_name if parent_function else None,
            "bases": bases,
            "keywords": [
                {"name": keyword.arg, "value": _expression(keyword.value)}
                for keyword in node.keywords
            ],
            "decorators": [_expression(item) for item in node.decorator_list],
            "docstring": ast.get_docstring(node),
            "methods": [],
            "nested_classes": [],
            "attributes": [],
            "parent_id": parent_scope.record["id"] if parent_scope.record else None,
            "method_ids": [],
            "nested_class_ids": [],
        }
        self.classes.append(record)
        if parent_scope.kind == "class" and parent_scope.record is not None:
            parent_scope.record["nested_classes"].append(qualified_name)
            parent_scope.record["nested_class_ids"].append(class_id)
        self._definitions.append(
            {
                "kind": "class",
                "name": qualified_name,
                "node_name": node.name,
                "line": node.lineno,
                "bases": bases,
                "decorators": [_decorator_info(item) for item in node.decorator_list],
            }
        )

        self.scopes.append(_Scope("class", qualified_name, record))
        with self._context_label("body"):
            for statement in node.body:
                self.visit(statement)
        self.scopes.pop()

    # -- assignments --------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        scope = self._scope
        if scope.kind == "module":
            self._module_assignment(node.targets, node.value, node.lineno, "")
        elif scope.kind == "class" and scope.record is not None:
            self._class_attributes(node.targets, node.value, node.lineno, "", scope.record)
        elif scope.kind == "function":
            enclosing_class = self._nearest("class")
            if enclosing_class is not None and enclosing_class.record is not None:
                self._method_self_attributes(node.targets, node.value, node.lineno, "", enclosing_class.record)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        scope = self._scope
        annotation = _expression(node.annotation)
        if scope.kind == "module":
            self._module_assignment([node.target], node.value, node.lineno, annotation)
        elif scope.kind == "class" and scope.record is not None:
            self._class_attributes([node.target], node.value, node.lineno, annotation, scope.record)
        elif scope.kind == "function":
            enclosing_class = self._nearest("class")
            if enclosing_class is not None and enclosing_class.record is not None:
                self._method_self_attributes([node.target], node.value, node.lineno, annotation, enclosing_class.record)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if (
            self._scope.kind == "module"
            and isinstance(node.target, ast.Name)
            and node.target.id == "urlpatterns"
        ):
            self._urlpatterns.append((node.lineno, node.value))
        self.generic_visit(node)

    @staticmethod
    def _method_self_attributes(
        targets: list[ast.expr],
        value: ast.expr | None,
        line: int,
        annotation: str,
        class_record: dict[str, Any],
    ) -> None:
        for target in targets:
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                name = target.attr
                if not any(attr["name"] == name for attr in class_record["attributes"]):
                    class_record["attributes"].append(
                        {
                            "name": name,
                            "line": line,
                            "annotation": annotation,
                            "value": _literal_representation(value) if value is not None else None,
                        }
                    )

    @staticmethod
    def _class_attributes(
        targets: list[ast.expr],
        value: ast.expr | None,
        line: int,
        annotation: str,
        class_record: dict[str, Any],
    ) -> None:
        for target in targets:
            for name in _target_names(target):
                class_record["attributes"].append(
                    {
                        "name": name,
                        "line": line,
                        "annotation": annotation,
                        "value": _literal_representation(value) if value is not None else None,
                    }
                )

    def _module_assignment(
        self,
        targets: list[ast.expr],
        value: ast.expr | None,
        line: int,
        annotation: str,
    ) -> None:
        for target in targets:
            for name in _target_names(target):
                self.globals.append(
                    {
                        "name": name,
                        "line": line,
                        "annotation": annotation,
                        "is_constant": name.isupper(),
                        "value": _literal_representation(value) if value is not None else None,
                    }
                )
                if name == "urlpatterns":
                    self._urlpatterns.append((line, value))
            # Remember ``app = Something(...)`` so decorators on ``app`` can be
            # attributed to a framework by what ``app`` was built from.
            if isinstance(target, ast.Name) and isinstance(value, ast.Call):
                self._call_assignments[target.id] = _expression(value.func)

    # -- framework hints ----------------------------------------------------

    def finalize(self) -> None:
        """Derive framework hints from the complete import table, then sort outputs."""
        table = _ImportTable(self.imports)
        origins = {name: table.resolve(callee) for name, callee in self._call_assignments.items()}
        click_groups = {
            item["node_name"]
            for item in self._definitions
            if item["kind"] == "function"
            and any(table.resolve(d["callee"]) == "click.group" for d in item["decorators"])
        }
        for item in self._definitions:
            if item["kind"] == "function":
                self._function_hints(item, table, origins, click_groups)
            else:
                self._class_hints(item, table)
        self._url_hints(table)

        self.framework_hints.sort(
            key=lambda item: (item["framework"], item["kind"], item["line"], item["name"])
        )
        self.imports.sort(key=lambda item: (item["line"], item["kind"], item["module"] or ""))
        self.functions.sort(key=lambda item: (item["line"], item["qualified_name"], item["kind"]))
        self.classes.sort(key=lambda item: (item["line"], item["qualified_name"]))
        self.calls.sort(key=lambda item: (item["line"], item["column"], item["name"]))
        self.globals.sort(key=lambda item: (item["line"], item["name"]))

    def _hint(
        self,
        framework: str,
        kind: str,
        name: str,
        line: int,
        confidence: str,
        evidence: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        hint: dict[str, Any] = {
            "framework": framework,
            "kind": kind,
            "name": name,
            "line": line,
            "confidence": confidence,
            "evidence": evidence,
        }
        if details:
            hint["details"] = details
        if hint not in self.framework_hints:
            self.framework_hints.append(hint)

    def _function_hints(
        self,
        item: dict[str, Any],
        table: _ImportTable,
        origins: dict[str, str | None],
        click_groups: set[str],
    ) -> None:
        name, line = item["name"], item["line"]
        for decorator in item["decorators"]:
            callee = decorator["callee"]
            receiver, _, attr = callee.rpartition(".")
            resolved = table.resolve(callee)

            route = self._route_evidence(receiver, attr, table, origins)
            if route is not None:
                framework, confidence, evidence = route
                details: dict[str, Any] = {}
                if decorator["path"] is not None:
                    details["path"] = decorator["path"]
                methods = [attr.upper()] if attr in _HTTP_METHODS else decorator["methods"]
                if methods:
                    details["methods"] = methods
                self._hint(framework, "route", name, line, confidence, evidence, details)

            task = self._celery_evidence(receiver, attr, resolved, table, origins)
            if task is not None:
                self._hint("celery", "task", name, line, *task)

            command = self._cli_evidence(receiver, attr, resolved, table, origins, click_groups)
            if command is not None:
                self._hint(command[0], "command", name, line, command[1], command[2])

            if resolved in _FIXTURE_DECORATORS:
                self._hint("pytest", "fixture", name, line, "high", f"decorator resolves to {resolved}")

        node_name = item["node_name"]
        if node_name.startswith("test_") or node_name.endswith("_test"):
            file_name = PurePosixPath(self.path).name
            if file_name.startswith("test_") or file_name.endswith("_test.py"):
                self._hint("pytest", "test", name, line, "high", "test-style function name in a test-style file name")
            else:
                self._hint("pytest", "test", name, line, "low", "test-style function name only; file name is not test-style")

    @staticmethod
    def _route_evidence(
        receiver: str,
        attr: str,
        table: _ImportTable,
        origins: dict[str, str | None],
    ) -> tuple[str, str, str] | None:
        if not receiver:
            return None
        if receiver in origins:
            origin = origins[receiver]
            if origin in _FASTAPI_APPS and attr in _FASTAPI_ATTRS:
                return "fastapi", "high", f"receiver '{receiver}' is assigned from {origin}()"
            if origin in _FLASK_APPS and attr in _FLASK_ATTRS:
                return "flask", "high", f"receiver '{receiver}' is assigned from {origin}()"
            return None  # receiver is known to be something else
        candidates = []
        if attr in _FASTAPI_ATTRS and table.imports_package("fastapi"):
            candidates.append("fastapi")
        if attr in _FLASK_ATTRS and table.imports_package("flask"):
            candidates.append("flask")
        if len(candidates) == 1:
            return (
                candidates[0],
                "low",
                f"file imports {candidates[0]}; origin of receiver '{receiver}' not established",
            )
        return None

    @staticmethod
    def _celery_evidence(
        receiver: str,
        attr: str,
        resolved: str | None,
        table: _ImportTable,
        origins: dict[str, str | None],
    ) -> tuple[str, str] | None:
        if resolved in {"celery.shared_task", "celery.task"}:
            return "high", f"decorator resolves to {resolved}"
        if attr == "task" and receiver:
            if receiver in origins:
                if origins[receiver] == "celery.Celery":
                    return "high", f"receiver '{receiver}' is assigned from celery.Celery()"
                return None
            if table.imports_package("celery"):
                return "low", f"file imports celery; origin of receiver '{receiver}' not established"
        return None

    @staticmethod
    def _cli_evidence(
        receiver: str,
        attr: str,
        resolved: str | None,
        table: _ImportTable,
        origins: dict[str, str | None],
        click_groups: set[str],
    ) -> tuple[str, str, str] | None:
        if resolved in _CLICK_DECORATORS:
            return "click", "high", f"decorator resolves to {resolved}"
        if not receiver or attr not in {"command", "group"}:
            return None
        if receiver in click_groups:
            return "click", "high", f"receiver '{receiver}' is a function decorated with click.group"
        if receiver in origins:
            if origins[receiver] == "typer.Typer" and attr == "command":
                return "typer", "high", f"receiver '{receiver}' is assigned from typer.Typer()"
            return None
        candidates = []
        if table.imports_package("click"):
            candidates.append("click")
        if attr == "command" and table.imports_package("typer"):
            candidates.append("typer")
        if len(candidates) == 1:
            return (
                candidates[0],
                "low",
                f"file imports {candidates[0]}; origin of receiver '{receiver}' not established",
            )
        return None

    def _class_hints(self, item: dict[str, Any], table: _ImportTable) -> None:
        name, line = item["name"], item["line"]
        for base in item["bases"]:
            if base.rsplit(".", 1)[-1] != "Model":
                continue
            resolved = table.resolve(base)
            if resolved == "django.db.models.Model":
                self._hint("django", "model", name, line, "high", f"base '{base}' resolves to {resolved}")
            elif table.imports_package("django"):
                self._hint("django", "model", name, line, "low", f"base named '{base}'; file imports django but base origin is unknown")
        for decorator in item["decorators"]:
            resolved = table.resolve(decorator["callee"])
            if resolved in _CLICK_DECORATORS:
                self._hint("click", "command", name, line, "high", f"decorator resolves to {resolved}")

    def _url_hints(self, table: _ImportTable) -> None:
        for line, value in self._urlpatterns:
            django_backed = False
            for child in ast.walk(value) if value is not None else []:
                if not isinstance(child, ast.Call):
                    continue
                call_name, _base, _receiver = _qualified_expression_name(child.func)
                short_name = call_name.rsplit(".", 1)[-1]
                if short_name not in _URL_FUNCTIONS:
                    continue
                resolved = table.resolve(call_name)
                if resolved is not None and resolved.startswith("django."):
                    confidence, evidence = "high", f"call resolves to {resolved}"
                    django_backed = True
                else:
                    confidence, evidence = "low", f"call named '{call_name}'; not resolved to django"
                details: dict[str, Any] = {}
                if short_name == "include":
                    if child.args:
                        details["include"] = _expression(child.args[0])
                else:
                    if child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str):
                        details["route"] = child.args[0].value
                    if len(child.args) > 1:
                        details["view"] = _expression(child.args[1])
                for kw in child.keywords:
                    if kw.arg == "name":
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            details["name"] = kw.value.value
                        else:
                            details["name"] = _expression(kw.value)
                    elif kw.arg == "namespace":
                        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            details["namespace"] = kw.value.value
                        else:
                            details["namespace"] = _expression(kw.value)
                self._hint("django", "url_pattern", call_name, child.lineno, confidence, evidence, details)
            if django_backed:
                self._hint("django", "url_patterns", "urlpatterns", line, "high", "urlpatterns contains django-resolved path()/re_path()/include() calls")
            else:
                self._hint("django", "url_patterns", "urlpatterns", line, "low", "module-level 'urlpatterns' assignment only (naming convention)")


# --------------------------------------------------------------------------- #
# Discovery, reading and per-file processing
# --------------------------------------------------------------------------- #


def _error(
    relative_path: str,
    error_type: str,
    message: str,
    line: int | None = None,
    column: int | None = None,
    *,
    severity: str = "error",
    stage: str = "read",
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "path": relative_path,
        "error_type": error_type,
        "message": message,
        "severity": severity,
        "stage": stage,
    }
    if line is not None:
        item["line"] = line
    if column is not None:
        item["column"] = column
    return item


def _display_path(filename: object, scan_root: Path) -> str:
    if not filename:
        return "."
    try:
        return Path(str(filename)).relative_to(scan_root).as_posix()
    except ValueError:
        return str(filename)


def _resolve_root(root: Path | str | None) -> Path:
    if root is None:
        scan_root = Path(__file__).resolve().parents[2] / "sample_repo"
        origin = "default sample_repo location (pass `root` explicitly to scan elsewhere)"
    else:
        scan_root = Path(root).expanduser().resolve()
        origin = "the `root` argument"
    if not scan_root.exists():
        raise NotADirectoryError(
            f"Repository root does not exist: {scan_root} (from {origin}). "
            "Pass the path of an existing directory."
        )
    if not scan_root.is_dir():
        raise NotADirectoryError(
            f"Repository root is not a directory: {scan_root} (from {origin}). "
            "Pass the repository directory, not a file."
        )
    return scan_root


def _resolve_max_file_size(max_file_size: int | None) -> int:
    if max_file_size is not None:
        if isinstance(max_file_size, bool) or not isinstance(max_file_size, int) or max_file_size <= 0:
            raise ValueError(f"max_file_size must be a positive integer number of bytes, got {max_file_size!r}")
        return max_file_size
    raw = os.environ.get(MAX_FILE_SIZE_ENV_VAR)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_FILE_SIZE
    try:
        value = int(raw.strip())
    except ValueError:
        value = 0
    if value <= 0:
        raise ValueError(
            f"{MAX_FILE_SIZE_ENV_VAR} must be a positive integer number of bytes, got {raw!r}"
        )
    return value


def _count_python_files(directory: Path) -> int:
    total = 0
    # os.walk ignores unreadable sub-directories and does not follow symlinks.
    for _current, _directories, names in os.walk(directory, followlinks=False):
        total += sum(1 for name in names if name.endswith(".py"))
    return total


def _discover_python_files(scan_root: Path) -> tuple[list[Path], int, list[dict[str, Any]]]:
    """Return ``(candidate files, skipped count, discovery errors)``.

    Symlinked directories are never entered (they could escape the repository
    or loop) and are not counted; symlinked ``.py`` files count as skipped.
    """
    candidates: list[Path] = []
    skipped = 0
    errors: list[dict[str, Any]] = []

    def on_error(exc: OSError) -> None:
        errors.append(
            _error(
                _display_path(exc.filename, scan_root),
                type(exc).__name__,
                str(exc),
                stage="discovery",
            )
        )

    for current, directories, filenames in os.walk(
        scan_root, topdown=True, followlinks=False, onerror=on_error
    ):
        current_path = Path(current)
        kept: list[str] = []
        for directory in sorted(directories):
            child = current_path / directory
            if child.is_symlink():
                logger.debug("Not following symlinked directory %s", child)
            elif directory in DEFAULT_IGNORED_DIRECTORIES:
                skipped += _count_python_files(child)
            else:
                kept.append(directory)
        directories[:] = kept

        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            candidate = current_path / filename
            if candidate.is_symlink():
                skipped += 1
                continue
            candidates.append(candidate)
    return candidates, skipped, errors


class _DecodedSource(NamedTuple):
    text: str
    encoding: str
    used_fallback: bool
    warnings: list[tuple[str, str]]  # (error_type, message)


def _decode_source(raw: bytes) -> _DecodedSource:
    """Decode Python source, preferring the declared encoding.

    Normal decoding (PEP 263 cookie / BOM via ``tokenize.detect_encoding``) is
    used whenever it succeeds and its result is returned unchanged. Otherwise
    the bytes are decoded as UTF-8 with U+FFFD replacement and a warning is
    returned. The result is *not* guaranteed to be valid Python.
    """
    problem: tuple[str, str]
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    except SyntaxError as exc:
        problem = ("EncodingDeclarationError", f"Could not determine source encoding: {exc.msg}")
    else:
        try:
            return _DecodedSource(raw.decode(encoding), encoding, False, [])
        except (UnicodeDecodeError, LookupError) as exc:
            problem = (type(exc).__name__, f"Could not decode source as {encoding}: {exc}")
    error_type, message = problem
    text = raw.decode(_FALLBACK_ENCODING, errors="replace")
    warning = (error_type, f"{message}; decoded as {_FALLBACK_ENCODING} with replacement characters")
    return _DecodedSource(text, _FALLBACK_ENCODING, True, [warning])


class _FileResult(NamedTuple):
    outcome: str  # "parsed" | "failed" | "skipped"
    record: dict[str, Any] | None
    diagnostics: list[dict[str, Any]]


def _process_file(path: Path, scan_root: Path, max_file_size: int) -> _FileResult:
    relative = path.relative_to(scan_root).as_posix()
    diagnostics: list[dict[str, Any]] = []

    def fail(error_type: str, message: str, stage: str, line: int | None = None, column: int | None = None) -> _FileResult:
        diagnostics.append(_error(relative, error_type, message, line, column, stage=stage))
        return _FileResult("failed", None, diagnostics)

    def skip_oversized() -> _FileResult:
        diagnostics.append(
            _error(
                relative,
                "FileTooLargeError",
                f"File exceeds {max_file_size} byte scan limit",
                severity="warning",
                stage="discovery",
            )
        )
        return _FileResult("skipped", None, diagnostics)

    try:
        file_stat = path.stat()
    except OSError as exc:  # vanished, permission denied, dangling link, ...
        return fail(type(exc).__name__, str(exc), "read")
    if not stat.S_ISREG(file_stat.st_mode):
        diagnostics.append(
            _error(relative, "NotARegularFileError", "Not a regular file; skipped", severity="warning", stage="discovery")
        )
        return _FileResult("skipped", None, diagnostics)
    if file_stat.st_size > max_file_size:
        return skip_oversized()

    try:
        with path.open("rb") as handle:
            raw = handle.read(max_file_size + 1)  # never loads more than limit + 1 bytes
    except OSError as exc:
        return fail(type(exc).__name__, str(exc), "read")
    if len(raw) > max_file_size:  # file grew after the stat() call
        return skip_oversized()
    if b"\0" in raw:
        return fail("ValueError", "Python source contains a null byte", "decode")

    decoded = _decode_source(raw)
    for error_type, message in decoded.warnings:
        diagnostics.append(_error(relative, error_type, message, severity="warning", stage="decode"))
    source = decoded.text

    module, is_package = _module_name(Path(relative))
    if not module and is_package:
        module = scan_root.name
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        return fail(type(exc).__name__, exc.msg, "parse", exc.lineno, exc.offset)
    except (ValueError, RecursionError) as exc:
        return fail(type(exc).__name__, str(exc), "parse")

    visitor = _SourceVisitor(relative, module, is_package)
    try:
        visitor.visit(tree)
        visitor.finalize()
    except RecursionError as exc:
        return fail(type(exc).__name__, f"AST too deeply nested to analyze: {exc}", "analyze")

    record = {
        "id": _stable_id("file", relative),
        "path": relative,
        "module": module,
        "is_package": is_package,
        "line_count": source.count("\n") + bool(source and not source.endswith("\n")),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "docstring": ast.get_docstring(tree),
        "imports": visitor.imports,
        "functions": visitor.functions,
        "classes": visitor.classes,
        "calls": visitor.calls,
        "globals": visitor.globals,
        "framework_hints": visitor.framework_hints,
        "encoding": decoded.encoding,
        "decode_fallback": decoded.used_fallback,
    }
    return _FileResult("parsed", record, diagnostics)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def parse_repository(
    root: Path | str | None = None,
    *,
    max_file_size: int | None = None,
) -> dict[str, Any]:
    """Parse Python source files without importing or executing the repository.

    Args:
        root: Repository directory to scan. Defaults to the ``sample_repo``
            directory beside the Cypher package.
        max_file_size: Maximum size in bytes of a source file to analyse.
            Larger files are skipped (counted in ``skipped_files``, reported
            with a warning). Falls back to the ``CYPHER_MAX_FILE_SIZE``
            environment variable, then to ``DEFAULT_MAX_FILE_SIZE``.

    Returns:
        A JSON-serializable mapping containing the absolute ``root``, sorted
        ``files`` and ``errors`` lists, and ``stats`` with file and AST-record
        counts. See the module docstring for the record schemas.

    Raises:
        NotADirectoryError: ``root`` does not exist or is not a directory.
        ValueError: ``max_file_size`` / ``CYPHER_MAX_FILE_SIZE`` is invalid.
        MemoryError: propagated deliberately; the run is not continued.
    """
    scan_root = _resolve_root(root)
    limit = _resolve_max_file_size(max_file_size)

    files: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    stats = {
        "scanned_files": 0,
        "parsed_files": 0,
        "failed_files": 0,
        "skipped_files": 0,
        "functions": 0,
        "classes": 0,
        "imports": 0,
        "calls": 0,
    }

    candidates, skipped, discovery_errors = _discover_python_files(scan_root)
    stats["skipped_files"] += skipped
    errors.extend(discovery_errors)
    for item in discovery_errors:
        logger.warning("Could not read directory %s: %s", item["path"], item["message"])

    for path in sorted(candidates, key=lambda item: item.relative_to(scan_root).as_posix()):
        result = _process_file(path, scan_root, limit)
        errors.extend(result.diagnostics)
        for item in result.diagnostics:
            logger.warning(
                "%s (%s) %s: %s", item["path"], item["stage"], item["error_type"], item["message"]
            )
        if result.outcome == "skipped":
            stats["skipped_files"] += 1
        elif result.outcome == "failed":
            stats["scanned_files"] += 1
            stats["failed_files"] += 1
        elif result.record is not None:
            stats["scanned_files"] += 1
            stats["parsed_files"] += 1
            files.append(result.record)
            stats["functions"] += len(result.record["functions"])
            stats["classes"] += len(result.record["classes"])
            stats["imports"] += len(result.record["imports"])
            stats["calls"] += len(result.record["calls"])

    files.sort(key=lambda item: item["path"])
    errors.sort(
        key=lambda item: (
            item["path"],
            item.get("line", 0),
            item["error_type"],
            item["message"],
        )
    )
    return {
        "root": str(scan_root),
        "files": files,
        "errors": errors,
        "stats": stats,
    }
