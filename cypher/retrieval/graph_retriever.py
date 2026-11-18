"""Graph retriever — queries Neo4j using predefined parameterized templates.

Security guarantee: this module NEVER executes LLM-generated Cypher.
All queries are hand-written templates parameterized with safe values.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from cypher.graph.neo4j_client import Neo4jClient
from cypher.schemas.rag import GraphResult, QueryUnderstanding

logger = logging.getLogger(__name__)


class GraphRetriever:
    """Retrieve code entities from Neo4j using the query understanding intent.

    All graph traversal is bounded by:
      - ``rag_graph_top_k`` results maximum.
      - Hard-coded ``max_depth`` cap (enforced upstream in ``_sanitize_understanding``).
      - Predefined query templates only — no dynamic Cypher generation.
    """

    def __init__(self, neo4j_client: Neo4jClient) -> None:
        self._client = neo4j_client

    def retrieve(
        self,
        understanding: QueryUnderstanding,
        repository_id: str,
        top_k: int = 10,
    ) -> list[GraphResult]:
        """Return graph entities relevant to the query understanding.

        Strategy:
          1. Direct entity lookup for each named entity in ``understanding.entities``.
          2. Caller / callee traversal based on relationship types and direction.
          3. Route-to-view lookup when intent == find_route.
          4. Class hierarchy when intent involves inheritance.
          5. All routes as fallback for architecture_overview intent.
        """
        start = time.monotonic()
        results: list[GraphResult] = []
        seen: set[str] = set()

        intent = understanding.intent
        entities = understanding.entities
        graph_cfg = understanding.graph_search
        depth = min(graph_cfg.max_depth, 3)

        # 1. Direct entity lookup for each named entity
        for entity_name in entities:
            rows = self._lookup_entity(entity_name, repository_id)
            for row in rows:
                r = _row_to_graph_result(row, "direct_match")
                key = _result_key(r)
                if key not in seen:
                    seen.add(key)
                    results.append(r)

        # 2. Caller / callee traversal
        if "CALLS" in graph_cfg.relationship_types or "INSTANTIATES" in graph_cfg.relationship_types:
            for entity_name in entities:
                if graph_cfg.direction in ("outgoing", "both"):
                    rows = self._find_callees(entity_name, repository_id, depth)
                    for row in rows:
                        r = _row_to_graph_result_callee(row)
                        key = _result_key(r)
                        if key not in seen:
                            seen.add(key)
                            results.append(r)

                if graph_cfg.direction in ("incoming", "both"):
                    rows = self._find_callers(entity_name, repository_id, depth)
                    for row in rows:
                        r = _row_to_graph_result_caller(row)
                        key = _result_key(r)
                        if key not in seen:
                            seen.add(key)
                            results.append(r)

        # 3. Impact analysis — both directions, deeper traversal
        if intent == "impact_analysis":
            for entity_name in entities:
                rows = self._find_callers(entity_name, repository_id, depth)
                for row in rows:
                    r = _row_to_graph_result_caller(row)
                    key = _result_key(r)
                    if key not in seen:
                        seen.add(key)
                        results.append(r)
                # Also find what this entity uses (downstream impact)
                rows = self._find_callees(entity_name, repository_id, depth)
                for row in rows:
                    r = _row_to_graph_result_callee(row)
                    key = _result_key(r)
                    if key not in seen:
                        seen.add(key)
                        results.append(r)

        # 4. Route lookup
        if intent in ("find_route", "architecture_overview") or "ROUTES_TO" in graph_cfg.relationship_types:
            rows = self._find_routes(repository_id)
            for row in rows:
                r = _row_to_graph_result_route(row)
                key = _result_key(r)
                if key not in seen:
                    seen.add(key)
                    results.append(r)

        # 5. Class hierarchy for class-related queries
        if "INHERITS" in graph_cfg.relationship_types:
            for entity_name in entities:
                rows = self._find_class_hierarchy(entity_name, repository_id)
                for row in rows:
                    for qname in (row.get("superclasses") or []) + (row.get("subclasses") or []):
                        if not qname:
                            continue
                        sub_rows = self._lookup_entity(qname, repository_id)
                        for sr in sub_rows:
                            r = _row_to_graph_result(sr, "inheritance")
                            key = _result_key(r)
                            if key not in seen:
                                seen.add(key)
                                results.append(r)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.debug(
            "GraphRetriever found %d results in %.1f ms (repo=%s)",
            len(results), elapsed_ms, repository_id,
        )

        return results[:top_k]

    # ------------------------------------------------------------------
    # Private query methods — all use parameterized Cypher
    # ------------------------------------------------------------------

    def _lookup_entity(self, name: str, repository_id: str) -> list[dict[str, Any]]:
        """Find entities by name or qualified_name."""
        cypher = """
        MATCH (e:Entity {repository_id: $repo_id})
        WHERE e.name = $name OR e.qualified_name = $name
          OR e.qualified_name ENDS WITH ('.' + $name)
          OR e.file_path = $name OR e.file_path ENDS WITH ('/' + $name)
          OR (e.file_path IS NOT NULL AND e.file_path CONTAINS $name)
        RETURN e.id AS entity_id,
               e.qualified_name AS qualified_name,
               e.file_path AS file_path,
               e.line AS start_line,
               e.end_line AS end_line,
               [lbl IN labels(e) WHERE lbl <> 'Entity'][0] AS symbol_type
        LIMIT 20
        """
        try:
            return self._client.execute_query(
                cypher, {"repo_id": repository_id, "name": name}
            )
        except Exception as exc:
            logger.warning("GraphRetriever._lookup_entity error: %s", exc)
            return []

    def _find_callees(
        self, entity_name: str, repository_id: str, depth: int
    ) -> list[dict[str, Any]]:
        """Find functions / classes called or instantiated by entity_name."""
        cypher = f"""
        MATCH (f:Entity {{repository_id: $repo_id}})
        WHERE f.name = $name OR f.qualified_name = $name
          OR f.qualified_name ENDS WITH ('.' + $name)
        MATCH path = (f)-[:CALLS|INSTANTIATES*1..{depth}]->(target:Entity)
        WHERE target.repository_id = $repo_id
        RETURN DISTINCT
               target.id AS entity_id,
               target.qualified_name AS qualified_name,
               target.file_path AS file_path,
               target.line AS start_line,
               target.end_line AS end_line,
               [lbl IN labels(target) WHERE lbl <> 'Entity'][0] AS symbol_type,
               length(path) AS depth
        ORDER BY depth, qualified_name
        LIMIT 20
        """
        try:
            return self._client.execute_query(
                cypher, {"repo_id": repository_id, "name": entity_name}
            )
        except Exception as exc:
            logger.warning("GraphRetriever._find_callees error: %s", exc)
            return []

    def _find_callers(
        self, entity_name: str, repository_id: str, depth: int
    ) -> list[dict[str, Any]]:
        """Find functions that call entity_name (up to `depth` hops)."""
        cypher = f"""
        MATCH (target:Entity {{repository_id: $repo_id}})
        WHERE target.name = $name OR target.qualified_name = $name
          OR target.qualified_name ENDS WITH ('.' + $name)
        MATCH path = (caller:Function {{repository_id: $repo_id}})-[:CALLS*1..{depth}]->(target)
        RETURN DISTINCT
               caller.id AS entity_id,
               caller.qualified_name AS qualified_name,
               caller.file_path AS file_path,
               caller.line AS start_line,
               caller.end_line AS end_line,
               'Function' AS symbol_type,
               length(path) AS depth
        ORDER BY depth, qualified_name
        LIMIT 20
        """
        try:
            return self._client.execute_query(
                cypher, {"repo_id": repository_id, "name": entity_name}
            )
        except Exception as exc:
            logger.warning("GraphRetriever._find_callers error: %s", exc)
            return []

    def _find_routes(self, repository_id: str) -> list[dict[str, Any]]:
        """Return all HTTP routes with their handler functions."""
        cypher = """
        MATCH (source:Entity)-[r:ROUTES_TO]->(target:Function)
        WHERE r.repository_id = $repo_id OR target.repository_id = $repo_id
        RETURN DISTINCT
               target.id AS entity_id,
               target.qualified_name AS qualified_name,
               target.file_path AS file_path,
               target.line AS start_line,
               target.end_line AS end_line,
               'Function' AS symbol_type,
               r.route AS route
        ORDER BY route
        LIMIT 30
        """
        try:
            return self._client.execute_query(
                cypher, {"repo_id": repository_id}
            )
        except Exception as exc:
            logger.warning("GraphRetriever._find_routes error: %s", exc)
            return []

    def _find_class_hierarchy(
        self, class_name: str, repository_id: str
    ) -> list[dict[str, Any]]:
        """Return superclasses and subclasses for a given class."""
        cypher = """
        MATCH (c:Class {repository_id: $repo_id})
        WHERE c.name = $name OR c.qualified_name = $name
          OR c.qualified_name ENDS WITH ('.' + $name)
        OPTIONAL MATCH (c)-[:INHERITS*1..3]->(super:Entity)
        OPTIONAL MATCH (sub:Class)-[:INHERITS*1..3]->(c)
        RETURN c.qualified_name AS class,
               collect(DISTINCT super.qualified_name) AS superclasses,
               collect(DISTINCT sub.qualified_name) AS subclasses
        LIMIT 1
        """
        try:
            return self._client.execute_query(
                cypher, {"repo_id": repository_id, "name": class_name}
            )
        except Exception as exc:
            logger.warning("GraphRetriever._find_class_hierarchy error: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Row → GraphResult converters
# ---------------------------------------------------------------------------

def _row_to_graph_result(row: dict[str, Any], rel_type: str = "") -> GraphResult:
    return GraphResult(
        entity_id=str(row.get("entity_id") or ""),
        qualified_name=str(row.get("qualified_name") or ""),
        file_path=str(row.get("file_path") or ""),
        start_line=int(row.get("start_line") or 0),
        end_line=int(row.get("end_line") or row.get("start_line") or 0),
        symbol_type=str(row.get("symbol_type") or "Function"),
        relationship_type=rel_type,
        score=1.0,
    )


def _row_to_graph_result_callee(row: dict[str, Any]) -> GraphResult:
    return _row_to_graph_result(row, "CALLS")


def _row_to_graph_result_caller(row: dict[str, Any]) -> GraphResult:
    return _row_to_graph_result(row, "CALLED_BY")


def _row_to_graph_result_route(row: dict[str, Any]) -> GraphResult:
    r = _row_to_graph_result(row, "ROUTES_TO")
    return r


def _result_key(r: GraphResult) -> str:
    return f"{r.file_path}:{r.start_line}:{r.end_line}"
