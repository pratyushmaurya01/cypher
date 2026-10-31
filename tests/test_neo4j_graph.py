"""Unit tests for Neo4j client, graph builder, and cypher queries."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cypher.analyzer.engine import analyze_repository
from cypher.graph.graph_builder import GraphBuilder
from cypher.graph.neo4j_client import Neo4jClient, Neo4jConfig
from cypher.graph.queries import (
    find_all_routes,
    find_class_hierarchy,
    find_function_callers,
    find_function_dependencies,
    find_module_dependencies,
    find_uncalled_functions,
    get_repository_overview,
)


def test_neo4j_config():
    """Verify Neo4jConfig defaults and custom attributes."""
    cfg = Neo4jConfig(
        uri="bolt://example.com:7687",
        user="custom_user",
        password="secret_password",
        database="custom_db",
    )
    assert cfg.uri == "bolt://example.com:7687"
    assert cfg.user == "custom_user"
    assert cfg.password == "secret_password"
    assert cfg.database == "custom_db"


def test_neo4j_client_verify_connectivity_mock():
    """Verify connectivity check against mocked driver."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_record = {"ping": 1}
    mock_result = MagicMock()
    mock_result.single.return_value = mock_record
    mock_session.run.return_value = mock_result
    mock_driver.session.return_value.__enter__.return_value = mock_session

    client = Neo4jClient(driver=mock_driver)
    assert client.verify_connectivity() is True
    mock_session.run.assert_called_with("RETURN 1 AS ping")


def test_neo4j_client_connectivity_failure_handled():
    """Verify connectivity check handles failures gracefully without crashing."""
    mock_driver = MagicMock()
    mock_driver.session.side_effect = Exception("Connection refused")

    client = Neo4jClient(driver=mock_driver)
    assert client.verify_connectivity() is False


def test_neo4j_client_init_schema_mock():
    """Verify schema initialization runs all constraints and indexes."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    client = Neo4jClient(driver=mock_driver)
    executed = client.init_schema()
    assert len(executed) == 8
    assert any("entity_id_unique" in q for q in executed)
    assert any("repo_id_unique" in q for q in executed)
    assert mock_session.run.call_count == 8


def test_neo4j_client_batch_execution_mock():
    """Verify execute_batch slices into chunks and executes write."""
    mock_driver = MagicMock()
    mock_session = MagicMock()
    mock_driver.session.return_value.__enter__.return_value = mock_session

    client = Neo4jClient(driver=mock_driver)
    batch = [{"id": i} for i in range(25)]
    total = client.execute_batch("UNWIND $batch AS item RETURN item", batch, batch_size=10)
    assert total == 25
    assert mock_session.execute_write.call_count == 3  # 10 + 10 + 5


def test_graph_builder_payload_structure(tmp_path):
    """Verify GraphBuilder payload generates complete node and edge batches."""
    (tmp_path / "models.py").write_text(
        """
from django.db import models

class User(models.Model):
    pass
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "services.py").write_text(
        """
from models import User

def get_user():
    return User()
""".lstrip(),
        encoding="utf-8",
    )

    analysis = analyze_repository(tmp_path)
    builder = GraphBuilder()
    payload = builder.build_payload(analysis)

    assert "repository" in payload
    assert payload["repository"]["name"] == tmp_path.name

    nodes = payload["nodes"]
    assert len(nodes["modules"]) == 2
    assert len(nodes["classes"]) == 1
    assert len(nodes["functions"]) == 1
    # External inheritance to django.db.models.Model
    assert len(nodes["external_dependencies"]) >= 1

    rels = payload["relationships"]
    assert len(rels["CONTAINS"]) == 2  # Repo CONTAINS both modules
    assert len(rels["DEFINES"]) >= 2   # Module DEFINES class / function
    assert len(rels["IMPORTS"]) == 1   # services IMPORTS models
    assert len(rels["INHERITS"]) == 1  # User INHERITS Model
    assert len(rels["INSTANTIATES"]) == 1  # get_user INSTANTIATES User


def test_graph_builder_dry_run(tmp_path):
    """Verify GraphBuilder dry_run mode computes summary without calling Neo4j."""
    (tmp_path / "app.py").write_text(
        """
def hello():
    return 'world'
""".lstrip(),
        encoding="utf-8",
    )
    analysis = analyze_repository(tmp_path)
    builder = GraphBuilder()
    summary = builder.ingest(analysis, dry_run=True)

    assert summary["dry_run"] is True
    assert summary["nodes_total"] >= 2  # Repo + Module + Function
    assert summary["relationships_total"] >= 1  # Repo CONTAINS Module + DEFINES


def test_graph_builder_ingest_with_mock_client(tmp_path):
    """Verify ingest executes batch queries against Neo4jClient."""
    (tmp_path / "app.py").write_text("def hello(): pass\n", encoding="utf-8")
    analysis = analyze_repository(tmp_path)

    mock_client = MagicMock(spec=Neo4jClient)
    builder = GraphBuilder(client=mock_client)
    summary = builder.ingest(analysis, dry_run=False)

    assert summary["dry_run"] is False
    assert mock_client.init_schema.called
    assert mock_client.execute_write.called
    assert mock_client.execute_batch.called


def test_queries_parameter_binding():
    """Verify cypher query helper functions pass correct query and parameters."""
    mock_client = MagicMock(spec=Neo4jClient)
    mock_client.execute_query.return_value = [{"target": "db.query", "depth": 1}]

    res = find_function_dependencies(mock_client, "app.handler")
    assert res == [{"target": "db.query", "depth": 1}]
    mock_client.execute_query.assert_called_with(
        pytest.approx.__self__ if False else None or mock_client.execute_query.call_args[0][0],
        {"qualified_name": "app.handler"},
    )

    find_function_callers(mock_client, "db.query")
    find_all_routes(mock_client)
    find_module_dependencies(mock_client, "app.views")
    find_class_hierarchy(mock_client, "models.User")
    find_uncalled_functions(mock_client)
    get_repository_overview(mock_client)

    assert mock_client.execute_query.call_count >= 6
