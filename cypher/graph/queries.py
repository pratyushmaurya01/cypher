"""Predefined Cypher queries and query helper functions for codebase analysis."""

from __future__ import annotations

from typing import Any

from cypher.graph.neo4j_client import Neo4jClient


# ---------------------------------------------------------------------------
# Predefined Cypher Query Templates
# ---------------------------------------------------------------------------

FUNCTION_DEPENDENCIES_QUERY = """
MATCH (f:Function {qualified_name: $qualified_name})
WHERE ($repository_id IS NULL OR f.repository_id = $repository_id)
MATCH path = (f)-[:CALLS|INSTANTIATES*1..3]->(target:Entity)
RETURN DISTINCT target.qualified_name AS target,
       [lbl IN labels(target) WHERE lbl <> 'Entity'][0] AS kind,
       target.file_path AS file,
       length(path) AS depth
ORDER BY depth, target
"""

FUNCTION_CALLERS_QUERY = """
MATCH (target:Function {qualified_name: $qualified_name})
WHERE ($repository_id IS NULL OR target.repository_id = $repository_id)
MATCH path = (caller:Function)-[:CALLS*1..3]->(target)
RETURN DISTINCT caller.qualified_name AS caller,
       caller.file_path AS file,
       length(path) AS depth
ORDER BY depth, caller
"""

ALL_ROUTES_QUERY = """
MATCH (source:Entity)-[r:ROUTES_TO]->(target:Function)
WHERE ($repository_id IS NULL OR r.repository_id = $repository_id)
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
WHERE ($repository_id IS NULL OR m.repository_id = $repository_id)
RETURN imported.qualified_name AS imported_module,
       imported.file_path AS file_path,
       r.confidence AS confidence
ORDER BY imported_module
"""

MODULE_REVERSE_IMPORTS_QUERY = """
MATCH (importer:Module)-[r:IMPORTS]->(m:Module {qualified_name: $module_name})
WHERE ($repository_id IS NULL OR m.repository_id = $repository_id)
RETURN importer.qualified_name AS importing_module,
       importer.file_path AS file_path
ORDER BY importing_module
"""

CLASS_HIERARCHY_QUERY = """
MATCH (c:Class {qualified_name: $class_name})
WHERE ($repository_id IS NULL OR c.repository_id = $repository_id)
OPTIONAL MATCH (c)-[:INHERITS*1..5]->(super:Entity)
OPTIONAL MATCH (sub:Class)-[:INHERITS*1..5]->(c)
RETURN c.qualified_name AS class,
       collect(DISTINCT super.qualified_name) AS superclasses,
       collect(DISTINCT sub.qualified_name) AS subclasses
"""

DEAD_CODE_CANDIDATES_QUERY = """
MATCH (f:Function:Entity)
WHERE NOT (f.is_external)
  AND ($repository_id IS NULL OR f.repository_id = $repository_id)
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
WHERE ($repository_id IS NULL OR r.id = $repository_id)
WITH r
OPTIONAL MATCH (m:Module {repository_id: r.id})
WITH r, count(DISTINCT m) AS total_modules
OPTIONAL MATCH (c:Class {repository_id: r.id})
WITH r, total_modules, count(DISTINCT c) AS total_classes
OPTIONAL MATCH (f:Function {repository_id: r.id})
WITH r, total_modules, total_classes, count(DISTINCT f) AS total_functions
OPTIONAL MATCH (x:ExternalDependency {repository_id: r.id})
WITH r, total_modules, total_classes, total_functions, count(DISTINCT x) AS total_externals
OPTIONAL MATCH ()-[rel:CALLS {repository_id: r.id}]->()
WITH r, total_modules, total_classes, total_functions, total_externals, count(DISTINCT rel) AS total_calls
OPTIONAL MATCH ()-[route:ROUTES_TO {repository_id: r.id}]->()
RETURN total_modules,
       total_classes,
       total_functions,
       total_externals,
       total_calls,
       count(DISTINCT route) AS total_routes
"""


# ---------------------------------------------------------------------------
# High-Level Helper Functions
# ---------------------------------------------------------------------------

def find_function_dependencies(
    client: Neo4jClient, qualified_name: str, repository_id: str | None = None
) -> list[dict[str, Any]]:
    """Return all functions and classes called or instantiated by `qualified_name`."""
    return client.execute_query(
        FUNCTION_DEPENDENCIES_QUERY,
        {"qualified_name": qualified_name, "repository_id": repository_id},
    )


def find_function_callers(
    client: Neo4jClient, qualified_name: str, repository_id: str | None = None
) -> list[dict[str, Any]]:
    """Return all functions calling `qualified_name` directly or transitively."""
    return client.execute_query(
        FUNCTION_CALLERS_QUERY,
        {"qualified_name": qualified_name, "repository_id": repository_id},
    )


def find_all_routes(
    client: Neo4jClient, repository_id: str | None = None
) -> list[dict[str, Any]]:
    """Return all HTTP endpoints and their handler functions."""
    return client.execute_query(ALL_ROUTES_QUERY, {"repository_id": repository_id})


def find_module_dependencies(
    client: Neo4jClient, module_name: str, repository_id: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Return both outgoing and incoming module imports for `module_name`."""
    outgoing = client.execute_query(
        MODULE_IMPORTS_QUERY,
        {"module_name": module_name, "repository_id": repository_id},
    )
    incoming = client.execute_query(
        MODULE_REVERSE_IMPORTS_QUERY,
        {"module_name": module_name, "repository_id": repository_id},
    )
    return {"imports": outgoing, "imported_by": incoming}


def find_class_hierarchy(
    client: Neo4jClient, class_name: str, repository_id: str | None = None
) -> list[dict[str, Any]]:
    """Return superclasses and subclasses for `class_name`."""
    return client.execute_query(
        CLASS_HIERARCHY_QUERY,
        {"class_name": class_name, "repository_id": repository_id},
    )


def find_uncalled_functions(
    client: Neo4jClient, repository_id: str | None = None
) -> list[dict[str, Any]]:
    """Return functions that are never called internally or connected to routes."""
    return client.execute_query(
        DEAD_CODE_CANDIDATES_QUERY, {"repository_id": repository_id}
    )


def delete_repository_graph(client: Neo4jClient, repository_id: str) -> None:
    """Detach and delete all nodes and relationships belonging to repository_id."""
    cypher = """
    MATCH (r:Repository {id: $repo_id})
    OPTIONAL MATCH (n:Entity {repository_id: $repo_id})
    DETACH DELETE n, r
    """
    client.execute_write(cypher, {"repo_id": repository_id})


def find_entities(
    client: Neo4jClient,
    repository_id: str,
    *,
    kind: str | None = None,
    file_path: str | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return paginated entity nodes filtered by kind and file_path."""
    cypher = """
    MATCH (e:Entity {repository_id: $repo_id})
    WHERE ($kind IS NULL OR $kind IN labels(e))
      AND ($file_path IS NULL OR e.file_path = $file_path)
    RETURN e.id AS id,
           e.repository_id AS repository_id,
           e.name AS name,
           e.qualified_name AS qualified_name,
           [lbl IN labels(e) WHERE lbl <> 'Entity'][0] AS kind,
           e.file_path AS file_path,
           e.line AS line,
           e.end_line AS end_line
    ORDER BY e.qualified_name
    SKIP $skip LIMIT $limit
    """
    return client.execute_query(
        cypher,
        {
            "repo_id": repository_id,
            "kind": kind,
            "file_path": file_path,
            "skip": skip,
            "limit": limit,
        },
    )


def get_entity_detail(
    client: Neo4jClient,
    repository_id: str,
    entity_id: str,
) -> dict[str, Any] | None:
    """Return an entity node along with its incoming and outgoing relationships."""
    node_cypher = """
    MATCH (e:Entity {repository_id: $repo_id, id: $entity_id})
    RETURN e.id AS id,
           e.repository_id AS repository_id,
           e.name AS name,
           e.qualified_name AS qualified_name,
           [lbl IN labels(e) WHERE lbl <> 'Entity'][0] AS kind,
           e.file_path AS file_path,
           e.line AS line,
           e.end_line AS end_line
    LIMIT 1
    """
    nodes = client.execute_query(node_cypher, {"repo_id": repository_id, "entity_id": entity_id})
    if not nodes:
        return None
    entity = nodes[0]

    incoming_cypher = """
    MATCH (src:Entity)-[r]->(e:Entity {repository_id: $repo_id, id: $entity_id})
    RETURN type(r) AS type,
           src.id AS source_id,
           src.qualified_name AS source_name,
           properties(r) AS properties
    LIMIT 200
    """
    incoming = client.execute_query(incoming_cypher, {"repo_id": repository_id, "entity_id": entity_id})

    outgoing_cypher = """
    MATCH (e:Entity {repository_id: $repo_id, id: $entity_id})-[r]->(dst:Entity)
    RETURN type(r) AS type,
           dst.id AS target_id,
           dst.qualified_name AS target_name,
           properties(r) AS properties
    LIMIT 200
    """
    outgoing = client.execute_query(outgoing_cypher, {"repo_id": repository_id, "entity_id": entity_id})

    return {
        "entity": entity,
        "incoming_relationships": incoming,
        "outgoing_relationships": outgoing,
    }


def find_file_dependencies(
    client: Neo4jClient,
    repository_id: str,
    file_path: str,
) -> dict[str, Any]:
    """Find files imported by and files importing the given file."""
    outgoing_cypher = """
    MATCH (m:Module {repository_id: $repo_id, file_path: $file_path})-[:IMPORTS]->(imp:Module)
    WHERE imp.file_path IS NOT NULL AND imp.file_path <> $file_path
    RETURN DISTINCT imp.file_path AS file
    ORDER BY file
    """
    incoming_cypher = """
    MATCH (src:Module {repository_id: $repo_id})-[:IMPORTS]->(m:Module {repository_id: $repo_id, file_path: $file_path})
    WHERE src.file_path IS NOT NULL AND src.file_path <> $file_path
    RETURN DISTINCT src.file_path AS file
    ORDER BY file
    """
    out_files = client.execute_query(outgoing_cypher, {"repo_id": repository_id, "file_path": file_path})
    in_files = client.execute_query(incoming_cypher, {"repo_id": repository_id, "file_path": file_path})

    return {
        "repository_id": repository_id,
        "file_path": file_path,
        "imported_files": [r["file"] for r in out_files if "file" in r],
        "imported_by_files": [r["file"] for r in in_files if "file" in r],
    }


def get_repository_overview(
    client: Neo4jClient, repository_id: str | None = None
) -> dict[str, Any]:
    """Return aggregated statistics on repository entities and relationships."""
    res = client.execute_query(
        REPOSITORY_OVERVIEW_QUERY, {"repository_id": repository_id}
    )
    return res[0] if res else {}
