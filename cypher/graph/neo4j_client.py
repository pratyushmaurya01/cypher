"""Neo4j driver connection management, schema initialization, and query execution."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    import neo4j
    from neo4j import Driver, GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:  # pragma: no cover
    NEO4J_AVAILABLE = False
    Driver = Any  # type: ignore
    GraphDatabase = Any  # type: ignore


@dataclass
class Neo4jConfig:
    """Connection parameters for Neo4j."""

    uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user: str = os.getenv("NEO4J_USER", "neo4j")
    password: str = os.getenv("NEO4J_PASSWORD", "password")
    database: str = os.getenv("NEO4J_DATABASE", "neo4j")


class Neo4jClient:
    """Manages connection, transactions, schema constraints, and queries for Neo4j."""

    def __init__(
        self,
        config: Neo4jConfig | None = None,
        driver: Driver | None = None,
    ) -> None:
        self.config = config or Neo4jConfig()
        self._driver: Driver | None = driver
        self._connected = driver is not None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self.connect()
        assert self._driver is not None
        return self._driver

    def connect(self) -> None:
        """Establish connection to Neo4j instance."""
        if not NEO4J_AVAILABLE:
            raise RuntimeError(
                "The 'neo4j' package is required to connect to Neo4j. Install with 'pip install neo4j'."
            )
        if self._driver is None:
            try:
                self._driver = GraphDatabase.driver(
                    self.config.uri,
                    auth=(self.config.user, self.config.password),
                )
                self._connected = True
                logger.info("Connected to Neo4j at %s", self.config.uri)
            except Exception as e:
                self._connected = False
                logger.error("Failed to connect to Neo4j: %s", e)
                raise

    def close(self) -> None:
        """Close driver connection."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            self._connected = False
            logger.info("Neo4j driver closed.")

    def __enter__(self) -> Neo4jClient:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def verify_connectivity(self) -> bool:
        """Health check verifying whether Neo4j is reachable and authenticated."""
        try:
            with self.driver.session(database=self.config.database) as session:
                result = session.run("RETURN 1 AS ping")
                record = result.single()
                return bool(record and record["ping"] == 1)
        except Exception as e:
            logger.warning("Neo4j connectivity check failed: %s", e)
            return False

    def init_schema(self) -> list[str]:
        """Creates unique constraints and indexes on nodes and relationships."""
        constraint_queries = [
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT repo_id_unique IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT module_id_unique IF NOT EXISTS FOR (m:Module) REQUIRE m.id IS UNIQUE",
            "CREATE CONSTRAINT class_id_unique IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT function_id_unique IF NOT EXISTS FOR (f:Function) REQUIRE f.id IS UNIQUE",
            "CREATE CONSTRAINT ext_id_unique IF NOT EXISTS FOR (x:ExternalDependency) REQUIRE x.id IS UNIQUE",
            "CREATE INDEX entity_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.name)",
            "CREATE INDEX entity_qual_idx IF NOT EXISTS FOR (e:Entity) ON (e.qualified_name)",
        ]

        executed: list[str] = []
        with self.driver.session(database=self.config.database) as session:
            for q in constraint_queries:
                try:
                    session.run(q)
                    executed.append(q)
                except Exception as e:
                    logger.warning("Schema query failed: %s (query: %s)", e, q)

        return executed

    def execute_query(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Executes a read query and returns records as dictionaries."""
        with self.driver.session(database=self.config.database) as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]

    def execute_write(
        self, query: str, parameters: dict[str, Any] | None = None
    ) -> Any:
        """Executes a write query within a write transaction."""
        with self.driver.session(database=self.config.database) as session:
            return session.execute_write(
                lambda tx: [dict(record) for record in tx.run(query, parameters or {})]
            )

    def execute_batch(
        self, query: str, batch: list[dict[str, Any]], batch_size: int = 1000
    ) -> int:
        """Executes a parameterized write query unwinding batches of items."""
        total = len(batch)
        if total == 0:
            return 0

        with self.driver.session(database=self.config.database) as session:
            for i in range(0, total, batch_size):
                chunk = batch[i : i + batch_size]
                session.execute_write(lambda tx: tx.run(query, {"batch": chunk}).consume())

        return total
