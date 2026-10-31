"""Orchestrates repository parsing, symbol indexing, and cross-file resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cypher.analyzer.ast_parser import parse_repository
from cypher.resolver.call_resolver import CallResolver
from cypher.resolver.django_url_resolver import DjangoUrlResolver
from cypher.resolver.fastapi_resolver import FastAPIResolver
from cypher.resolver.flask_resolver import FlaskResolver
from cypher.resolver.import_resolver import ImportResolver
from cypher.resolver.relationship_builder import RelationshipBuilder
from cypher.resolver.symbol_index import SymbolIndex


def analyze_repository(
    root: Path | str | None = None,
    *,
    max_file_size: int | None = None,
) -> dict[str, Any]:
    """Run full static analysis pipeline on a repository.

    Steps:
    1. parse_repository() -> raw AST file records & framework hints
    2. SymbolIndex() -> repository-wide index of modules, classes, functions
    3. ImportResolver() -> resolve imports per file
    4. CallResolver() -> resolve function/method calls
    5. DjangoUrlResolver() -> resolve URL patterns & include() targets
    6. RelationshipBuilder() -> construct graph entities & relationships

    Returns graph-ready JSON-serializable dict.
    """
    scan_root = Path.cwd() if root is None else Path(root).resolve()

    # 1. Parse repository
    parse_result = parse_repository(scan_root, max_file_size=max_file_size)
    files = parse_result.get("files", [])
    files_by_path = {f.get("path", ""): f for f in files}

    # 2. Build Symbol Index
    index = SymbolIndex(files)

    # 3. Create resolvers
    import_resolver = ImportResolver(index)
    call_resolver = CallResolver(index, import_resolver)
    url_resolver = DjangoUrlResolver(index, import_resolver)
    fastapi_resolver = FastAPIResolver(index, import_resolver)
    flask_resolver = FlaskResolver(index, import_resolver)

    # 4. Resolve calls across all files
    all_calls = []
    for f in files:
        all_calls.extend(call_resolver.resolve_calls(f, files_by_path))

    # 5. Resolve URL patterns: Django + FastAPI + Flask
    url_results = url_resolver.resolve_urls(files)
    url_results += fastapi_resolver.resolve_all(files)
    url_results += flask_resolver.resolve_all(files)

    # 6. Build relationships and unified graph structure
    builder = RelationshipBuilder(index)
    graph = builder.build(
        call_results=all_calls,
        url_results=url_results,
        all_files=files_by_path,
        root=str(scan_root),
    )

    # Include parse diagnostics/errors
    graph["diagnostics"] = parse_result.get("errors", [])
    graph["stats"]["scanned_files"] = parse_result.get("stats", {}).get("scanned_files", len(files))
    graph["stats"]["failed_files"] = parse_result.get("stats", {}).get("failed_files", 0)

    return graph    
