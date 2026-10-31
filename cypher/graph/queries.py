"""Predefined Cypher queries and query helper functions for codebase analysis."""

from __future__ import annotations

from typing import Any

from cypher.graph.neo4j_client import Neo4jClient


# ---------------------------------------------------------------------------
# Predefined Cypher Query Templates
# ---------------------------------------------------------------------------

FUNCTION_DEPENDENCIES_QUERY = """
MATCH (f:Function {qualified_name: $qualified_name})
MATCH path = (f)-[:CALLS|INSTANTIATES*1..3]->(target:Entity)
RETURN DISTINCT target.qualified_name AS target,
       target.kind AS kind,
       target.file_path AS file,
       length(path) AS depth
ORDER BY depth, target
"""

FUNCTION_CALLERS_QUERY = """
MATCH (target:Function {qualified_name: $qualified_name})
MATCH path = (caller:Function)-[:CALLS*1..3]->(target)
RETURN DISTINCT caller.qualified_name AS caller,
       caller.file_path AS file,
       length(path) AS depth
ORDER BY depth, caller
"""

ALL_ROUTES_QUERY = """
MATCH (source:Entity)-[r:ROUTES_TO]->(target:Function)
RETURN source.qualified_name AS source,
       r.route AS route,
       r.http_methods AS http_methods,
       r.url_name AS url_name,
       target.qualified_name AS handler,
       target.file_path AS file
ORDER BY route, handler
"""

MODULE_IMPORTS_QUERY = """
MATCH (m:Module {qualified_name: $module_name})-[r:IMPORTS]->(imported:Module)
RETURN imported.qualified_name AS imported_module,
       imported.file_path AS file_path,
       r.confidence AS confidence
ORDER BY imported_module
"""

MODULE_REVERSE_IMPORTS_QUERY = """
MATCH (importer:Module)-[r:IMPORTS]->(m:Module {qualified_name: $module_name})
RETURN importer.qualified_name AS importing_module,
       importer.file_path AS file_path
ORDER BY importing_module
"""

CLASS_HIERARCHY_QUERY = """
MATCH (c:Class {qualified_name: $class_name})
OPTIONAL MATCH (c)-[:INHERITS*1..5]->(super:Entity)
OPTIONAL MATCH (sub:Class)-[:INHERITS*1..5]->(c)
RETURN c.qualified_name AS class,
       collect(DISTINCT super.qualified_name) AS superclasses,
       collect(DISTINCT sub.qualified_name) AS subclasses
"""

DEAD_CODE_CANDIDATES_QUERY = """
MATCH (f:Function:Entity)
WHERE NOT (f.is_external)
  AND NOT (:Entity)-[:CALLS]->(f)
  AND NOT (:Entity)-[:ROUTES_TO]->(f)
  AND NOT f.name STARTS WITH 'test_'
  AND NOT f.name STARTS WITH '__'
RETURN f.qualified_name AS unused_function,
       f.file_path AS file,
       f.line AS line
ORDER BY file, line
"""

REPOSITORY_OVERVIEW_QUERY = """
MATCH (r:Repository)
OPTIONAL MATCH (m:Module)
OPTIONAL MATCH (c:Class)
OPTIONAL MATCH (f:Function)
OPTIONAL MATCH (x:ExternalDependency)
OPTIONAL MATCH ()-[rel:CALLS]->()
OPTIONAL MATCH ()-[route:ROUTES_TO]->()
RETURN count(DISTINCT m) AS total_modules,
       count(DISTINCT c) AS total_classes,
       count(DISTINCT f) AS total_functions,
       count(DISTINCT x) AS total_externals,
       count(DISTINCT rel) AS total_calls,
       count(DISTINCT route) AS total_routes
"""


# ---------------------------------------------------------------------------
# High-Level Helper Functions
# ---------------------------------------------------------------------------

def find_function_dependencies(
    client: Neo4jClient, qualified_name: str
) -> list[dict[str, Any]]:
    """Return all functions and classes called or instantiated by `qualified_name`."""
    return client.execute_query(
        FUNCTION_DEPENDENCIES_QUERY, {"qualified_name": qualified_name}
    )


def find_function_callers(
    client: Neo4jClient, qualified_name: str
) -> list[dict[str, Any]]:
    """Return all functions calling `qualified_name` directly or transitively."""
    return client.execute_query(
        FUNCTION_CALLERS_QUERY, {"qualified_name": qualified_name}
    )


def find_all_routes(client: Neo4jClient) -> list[dict[str, Any]]:
    """Return all HTTP endpoints and their handler functions."""
    return client.execute_query(ALL_ROUTES_QUERY)


def find_module_dependencies(
    client: Neo4jClient, module_name: str
) -> dict[str, list[dict[str, Any]]]:
    """Return both outgoing and incoming module imports for `module_name`."""
    outgoing = client.execute_query(MODULE_IMPORTS_QUERY, {"module_name": module_name})
    incoming = client.execute_query(
        MODULE_REVERSE_IMPORTS_QUERY, {"module_name": module_name}
    )
    return {"imports": outgoing, "imported_by": incoming}


def find_class_hierarchy(
    client: Neo4jClient, class_name: str
) -> list[dict[str, Any]]:
    """Return superclasses and subclasses for `class_name`."""
    return client.execute_query(CLASS_HIERARCHY_QUERY, {"class_name": class_name})


def find_uncalled_functions(client: Neo4jClient) -> list[dict[str, Any]]:
    """Return functions that are never called internally or connected to routes."""
    return client.execute_query(DEAD_CODE_CANDIDATES_QUERY)


def get_repository_overview(client: Neo4jClient) -> dict[str, Any]:
    """Return aggregated statistics on repository entities and relationships."""
    res = client.execute_query(REPOSITORY_OVERVIEW_QUERY)
    return res[0] if res else {}
