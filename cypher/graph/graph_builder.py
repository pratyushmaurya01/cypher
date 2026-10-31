"""Transforms graph-ready analysis JSON into Neo4j nodes and relationships."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from cypher.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


def _stable_id(kind: str, *parts: object) -> str:
    value = "\0".join((kind, *(str(part) for part in parts)))
    return f"{kind}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:20]}"


class GraphBuilder:
    """Builds and executes idempotent Cypher batch ingestion for repository graphs."""

    def __init__(self, client: Neo4jClient | None = None) -> None:
        self.client = client

    def build_payload(self, analysis_result: dict[str, Any]) -> dict[str, Any]:
        """Prepares parameterized batches for nodes and relationships without executing them."""
        repo_meta = analysis_result.get("repository", {})
        repo_root = repo_meta.get("root", "")
        repo_id = _stable_id("repo", repo_root or "root")

        repo_node = {
            "id": repo_id,
            "root": repo_root,
            "files_count": repo_meta.get("files_count", 0),
            "name": repo_root.replace("\\", "/").rstrip("/").split("/")[-1] if repo_root else "repository",
        }

        # Segregate entities by target node label
        modules: list[dict[str, Any]] = []
        classes: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []
        external_dependencies: list[dict[str, Any]] = []

        # Repository CONTAINS Module edges
        contains_edges: list[dict[str, Any]] = []

        for entity in analysis_result.get("entities", []):
            is_ext = entity.get("is_external", False)
            props = {
                "id": entity["id"],
                "name": entity.get("name", ""),
                "qualified_name": entity.get("qualified_name", ""),
                "file_path": entity.get("file_path", ""),
                "line": entity.get("line") or 1,
                "is_external": is_ext,
                "docstring": entity.get("docstring") or "",
            }

            kind = entity.get("kind", "")
            if kind == "module":
                if is_ext:
                    external_dependencies.append(props)
                else:
                    props["is_package"] = entity.get("is_package", False)
                    modules.append(props)
                    contains_edges.append(
                        {
                            "id": _stable_id("rel_contains", repo_id, entity["id"]),
                            "source_id": repo_id,
                            "target_id": entity["id"],
                            "type": "CONTAINS",
                            "properties": {"type": "CONTAINS"},
                        }
                    )
            elif kind == "class":
                props["bases"] = entity.get("bases", [])
                props["decorators"] = entity.get("decorators", [])
                if is_ext:
                    external_dependencies.append(props)
                else:
                    classes.append(props)
            elif kind in ("function", "async_function"):
                props["is_method"] = entity.get("is_method", False)
                props["decorators"] = entity.get("decorators", [])
                props["return_annotation"] = entity.get("return_annotation") or ""
                functions.append(props)
            else:
                external_dependencies.append(props)

        # Segregate relationships by type
        relationships_by_type: dict[str, list[dict[str, Any]]] = {
            "CONTAINS": contains_edges,
            "DEFINES": [],
            "DEFINES_METHOD": [],
            "IMPORTS": [],
            "INHERITS": [],
            "CALLS": [],
            "INSTANTIATES": [],
            "ROUTES_TO": [],
            "INCLUDES": [],
        }

        for rel in analysis_result.get("relationships", []):
            rel_type = rel.get("type", "RELATED_TO")
            meta = rel.get("metadata", {})
            props = {
                "id": rel["id"],
                "type": rel_type,
                "line": rel.get("line") or 1,
                "confidence": rel.get("confidence", "high"),
                "method": rel.get("method", ""),
                "evidence": rel.get("evidence", ""),
                "route": meta.get("route") or "",
                "url_name": meta.get("url_name") or "",
                "http_methods": meta.get("http_methods") or [],
            }
            item = {
                "id": rel["id"],
                "source_id": rel["source_id"],
                "target_id": rel["target_id"],
                "type": rel_type,
                "properties": props,
            }
            relationships_by_type.setdefault(rel_type, []).append(item)

        return {
            "repository": repo_node,
            "nodes": {
                "modules": modules,
                "classes": classes,
                "functions": functions,
                "external_dependencies": external_dependencies,
            },
            "relationships": relationships_by_type,
        }

    def ingest(
        self,
        analysis_result: dict[str, Any],
        *,
        dry_run: bool = False,
        clear_existing_repo: bool = False,
    ) -> dict[str, Any]:
        """Ingests the static analysis graph into Neo4j with idempotent MERGE operations."""
        payload = self.build_payload(analysis_result)

        total_nodes = (
            1  # Repository
            + len(payload["nodes"]["modules"])
            + len(payload["nodes"]["classes"])
            + len(payload["nodes"]["functions"])
            + len(payload["nodes"]["external_dependencies"])
        )
        total_rels = sum(len(items) for items in payload["relationships"].values())

        summary = {
            "dry_run": dry_run,
            "repository_id": payload["repository"]["id"],
            "nodes_total": total_nodes,
            "nodes_by_label": {
                "Repository": 1,
                "Module": len(payload["nodes"]["modules"]),
                "Class": len(payload["nodes"]["classes"]),
                "Function": len(payload["nodes"]["functions"]),
                "ExternalDependency": len(payload["nodes"]["external_dependencies"]),
            },
            "relationships_total": total_rels,
            "relationships_by_type": {
                k: len(v) for k, v in payload["relationships"].items() if len(v) > 0
            },
        }

        if dry_run:
            logger.info("Dry run completed: %s", summary)
            return summary

        if self.client is None:
            raise RuntimeError("A connected Neo4jClient is required to ingest data.")

        # Ensure schema constraints exist
        self.client.init_schema()

        repo_id = payload["repository"]["id"]

        if clear_existing_repo:
            self.client.execute_write(
                """
                MATCH (r:Repository {id: $repo_id})
                OPTIONAL MATCH (r)-[:CONTAINS*1..2]->(n:Entity)
                DETACH DELETE n, r
                """,
                {"repo_id": repo_id},
            )

        # 1. Ingest Repository Node
        self.client.execute_write(
            """
            MERGE (r:Repository:Entity {id: $repo.id})
            ON CREATE SET r += $repo, r.created_at = timestamp()
            ON MATCH SET r += $repo, r.updated_at = timestamp()
            """,
            {"repo": payload["repository"]},
        )

        # 2. Ingest Module Nodes
        if payload["nodes"]["modules"]:
            self.client.execute_batch(
                """
                UNWIND $batch AS item
                MERGE (m:Module:Entity {id: item.id})
                ON CREATE SET m += item, m.created_at = timestamp()
                ON MATCH SET m += item, m.updated_at = timestamp()
                """,
                payload["nodes"]["modules"],
            )

        # 3. Ingest Class Nodes
        if payload["nodes"]["classes"]:
            self.client.execute_batch(
                """
                UNWIND $batch AS item
                MERGE (c:Class:Entity {id: item.id})
                ON CREATE SET c += item, c.created_at = timestamp()
                ON MATCH SET c += item, c.updated_at = timestamp()
                """,
                payload["nodes"]["classes"],
            )

        # 4. Ingest Function Nodes
        if payload["nodes"]["functions"]:
            self.client.execute_batch(
                """
                UNWIND $batch AS item
                MERGE (f:Function:Entity {id: item.id})
                ON CREATE SET f += item, f.created_at = timestamp()
                ON MATCH SET f += item, f.updated_at = timestamp()
                """,
                payload["nodes"]["functions"],
            )

        # 5. Ingest External Dependencies
        if payload["nodes"]["external_dependencies"]:
            self.client.execute_batch(
                """
                UNWIND $batch AS item
                MERGE (x:ExternalDependency:Entity {id: item.id})
                ON CREATE SET x += item, x.created_at = timestamp()
                ON MATCH SET x += item, x.updated_at = timestamp()
                """,
                payload["nodes"]["external_dependencies"],
            )

        # 6. Ingest Relationships by Type
        relationship_cypher_templates = {
            "CONTAINS": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:CONTAINS {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "DEFINES": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:DEFINES {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "DEFINES_METHOD": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:DEFINES_METHOD {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "IMPORTS": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:IMPORTS {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "INHERITS": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:INHERITS {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "CALLS": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:CALLS {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "INSTANTIATES": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:INSTANTIATES {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "ROUTES_TO": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:ROUTES_TO {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
            "INCLUDES": """
                UNWIND $batch AS item
                MATCH (source:Entity {id: item.source_id})
                MATCH (target:Entity {id: item.target_id})
                MERGE (source)-[r:INCLUDES {id: item.id}]->(target)
                ON CREATE SET r += item.properties, r.created_at = timestamp()
                ON MATCH SET r += item.properties, r.updated_at = timestamp()
            """,
        }

        for rel_type, items in payload["relationships"].items():
            if not items:
                continue
            cypher = relationship_cypher_templates.get(rel_type)
            if not cypher:
                cypher = f"""
                    UNWIND $batch AS item
                    MATCH (source:Entity {{id: item.source_id}})
                    MATCH (target:Entity {{id: item.target_id}})
                    MERGE (source)-[r:{rel_type} {{id: item.id}}]->(target)
                    ON CREATE SET r += item.properties, r.created_at = timestamp()
                    ON MATCH SET r += item.properties, r.updated_at = timestamp()
                """
            self.client.execute_batch(cypher, items)

        logger.info("Ingestion completed successfully: %s", summary)
        return summary
