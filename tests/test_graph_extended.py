"""Tests for Phase 3: Extended Graph Exploration APIs and Diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cypher.core.security import create_access_token, hash_password
from cypher.db.models import Base, RepositoryMetadata, User
from cypher.db.session import get_db
from cypher.main import create_app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client_with_graph_data(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session

    user = User(
        email="p3_user@example.com",
        hashed_password=hash_password("Pass1234"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    repo = RepositoryMetadata(
        repository_id="repo_graph_test",
        owner_id=user.id,
        name="graph_repo",
        status="analyzed",
    )
    db_session.add(repo)
    db_session.commit()

    token = create_access_token(subject=user.id, extra_claims={"email": user.email})
    headers = {"Authorization": f"Bearer {token}"}

    mock_neo4j = MagicMock()
    mock_neo4j.verify_connectivity.return_value = True

    # Pre-configure mock returns for graph exploration queries
    def execute_query_side_effect(query, params=None):
        params = params or {}
        if "MATCH (e:Entity" in query and "SKIP $skip LIMIT $limit" in query:
            return [
                {
                    "id": "func_1",
                    "repository_id": "repo_graph_test",
                    "name": "login_view",
                    "qualified_name": "users.views.login_view",
                    "kind": "Function",
                    "file_path": "users/views.py",
                    "line": 10,
                    "end_line": 25,
                }
            ]
        elif "MATCH (e:Entity" in query and "LIMIT 1" in query:
            if params.get("entity_id") == "func_1":
                return [
                    {
                        "id": "func_1",
                        "repository_id": "repo_graph_test",
                        "name": "login_view",
                        "qualified_name": "users.views.login_view",
                        "kind": "Function",
                        "file_path": "users/views.py",
                        "line": 10,
                        "end_line": 25,
                    }
                ]
            return []
        elif "MATCH (src:Entity)-[r]->" in query:
            return [
                {
                    "type": "CALLS",
                    "source_id": "caller_1",
                    "source_name": "app.main",
                    "properties": {},
                }
            ]
        elif "MATCH (e:Entity" in query and "-[r]->(dst:Entity)" in query:
            return [
                {
                    "type": "CALLS",
                    "target_id": "target_1",
                    "target_name": "users.services.auth",
                    "properties": {},
                }
            ]
        elif "MATCH (m:Module" in query and "-[:IMPORTS]->(imp:Module)" in query:
            return [{"file": "users/services.py"}]
        elif "MATCH (src:Module" in query and "-[:IMPORTS]->(m:Module" in query:
            return [{"file": "core/main.py"}]
        return []

    mock_neo4j.execute_query.side_effect = execute_query_side_effect

    with TestClient(app, raise_server_exceptions=True) as tc:
        tc.app.state.neo4j_client = mock_neo4j
        yield tc, user, headers


class TestPhase3GraphExploration:
    """Verifies entity listing, entity detail with relationships, and file dependencies."""

    def test_list_entities_endpoint(self, client_with_graph_data):
        client, _, headers = client_with_graph_data
        res = client.get(
            "/api/v1/graph/entities?repository_id=repo_graph_test&kind=Function&skip=0&limit=50",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["id"] == "func_1"
        assert data[0]["kind"] == "Function"
        assert data[0]["name"] == "login_view"

    def test_get_entity_detail_success(self, client_with_graph_data):
        client, _, headers = client_with_graph_data
        res = client.get(
            "/api/v1/graph/entity/func_1?repository_id=repo_graph_test",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["entity"]["id"] == "func_1"
        assert len(data["incoming_relationships"]) == 1
        assert data["incoming_relationships"][0]["type"] == "CALLS"
        assert len(data["outgoing_relationships"]) == 1
        assert data["outgoing_relationships"][0]["type"] == "CALLS"

    def test_get_entity_detail_not_found(self, client_with_graph_data):
        client, _, headers = client_with_graph_data
        res = client.get(
            "/api/v1/graph/entity/non_existent?repository_id=repo_graph_test",
            headers=headers,
        )
        assert res.status_code == 404

    def test_get_file_dependencies_endpoint(self, client_with_graph_data):
        client, _, headers = client_with_graph_data
        res = client.get(
            "/api/v1/graph/file/dependencies?repository_id=repo_graph_test&file_path=users/views.py",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["file_path"] == "users/views.py"
        assert data["imported_files"] == ["users/services.py"]
        assert data["imported_by_files"] == ["core/main.py"]
