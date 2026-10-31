"""Cypher graph package: Neo4j client, graph builder, and queries."""

from cypher.graph.graph_builder import GraphBuilder
from cypher.graph.neo4j_client import Neo4jClient, Neo4jConfig
from cypher.graph.queries import (
    ALL_ROUTES_QUERY,
    CLASS_HIERARCHY_QUERY,
    DEAD_CODE_CANDIDATES_QUERY,
    FUNCTION_CALLERS_QUERY,
    FUNCTION_DEPENDENCIES_QUERY,
    MODULE_IMPORTS_QUERY,
    MODULE_REVERSE_IMPORTS_QUERY,
    REPOSITORY_OVERVIEW_QUERY,
    find_all_routes,
    find_class_hierarchy,
    find_function_callers,
    find_function_dependencies,
    find_module_dependencies,
    find_uncalled_functions,
    get_repository_overview,
)

__all__ = [
    "Neo4jClient",
    "Neo4jConfig",
    "GraphBuilder",
    "FUNCTION_DEPENDENCIES_QUERY",
    "FUNCTION_CALLERS_QUERY",
    "ALL_ROUTES_QUERY",
    "MODULE_IMPORTS_QUERY",
    "MODULE_REVERSE_IMPORTS_QUERY",
    "CLASS_HIERARCHY_QUERY",
    "DEAD_CODE_CANDIDATES_QUERY",
    "REPOSITORY_OVERVIEW_QUERY",
    "find_function_dependencies",
    "find_function_callers",
    "find_all_routes",
    "find_module_dependencies",
    "find_class_hierarchy",
    "find_uncalled_functions",
    "get_repository_overview",
]
