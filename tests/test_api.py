"""API tests using FastAPI TestClient.

These tests do NOT require a running server or a live Neo4j connection.
The Neo4j client and analysis engine are mocked where needed.

Run with:
    pytest tests/test_api.py -v
"""

from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cypher.main import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(files: dict[str, str]) -> bytes:
    """Create an in-memory ZIP containing the given filename → content pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """TestClient with Neo4j mocked — no real database required."""
    app = create_app()
    mock_neo4j = MagicMock()
    mock_neo4j.verify_connectivity.return_value = True
    with TestClient(app, raise_server_exceptions=True) as test_client:
        test_client.app.state.neo4j_client = mock_neo4j
        yield test_client


@pytest.fixture()
def client_neo4j_down():
    """TestClient where Neo4j is unreachable."""
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as test_client:
        test_client.app.state.neo4j_client = None
        yield test_client


# Minimal fake result returned by the mocked analysis engine
_FAKE_ANALYSIS_RESULT = {
    "repository": {"root": "/tmp/fake", "files_count": 2},
    "entities": [],
    "relationships": [],
    "unresolved_references": [],
    "diagnostics": [],
    "stats": {
        "total_entities": 3,
        "entities_by_kind": {"module": 2, "function": 1},
        "total_relationships": 2,
        "relationships_by_type": {"DEFINES": 1, "CONTAINS": 1},
        "unresolved_calls": 0,
        "external_calls": 0,
        "ambiguous_calls": 0,
        "validation_errors": 0,
        "scanned_files": 2,
        "failed_files": 0,
    },
}

_FAKE_INGESTION_SUMMARY = {
    "dry_run": False,
    "repository_id": "repo_abc123",
    "nodes_total": 4,
    "nodes_by_label": {"Repository": 1, "Module": 2, "Function": 1},
    "relationships_total": 2,
    "relationships_by_type": {"CONTAINS": 2},
}


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200

    def test_health_ok_when_neo4j_connected(self, client):
        data = client.get("/api/v1/health").json()
        assert data["status"] == "ok"
        assert data["neo4j"] == "connected"
        assert data["version"] == "0.1.0"

    def test_health_degraded_when_neo4j_down(self, client_neo4j_down):
        response = client_neo4j_down.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["neo4j"] == "unreachable"

    def test_health_degraded_when_neo4j_raises(self, client):
        client.app.state.neo4j_client.verify_connectivity.side_effect = Exception("timeout")
        data = client.get("/api/v1/health").json()
        assert data["status"] == "degraded"
        assert data["neo4j"] == "unreachable"

    def test_health_response_shape(self, client):
        data = client.get("/api/v1/health").json()
        assert set(data.keys()) == {"status", "neo4j", "version"}


# ---------------------------------------------------------------------------
# Repository upload and analysis endpoint tests
# ---------------------------------------------------------------------------

class TestRepositoryUploadAndAnalyze:
    """Tests for POST /api/v1/repository/upload-and-analyze."""

    @pytest.fixture(autouse=True)
    def mock_analysis(self):
        with (
            patch(
                "cypher.services.analysis_service.analyze_repository",
                return_value=_FAKE_ANALYSIS_RESULT,
            ) as mock_engine,
            patch(
                "cypher.services.analysis_service.GraphBuilder.ingest",
                return_value=_FAKE_INGESTION_SUMMARY,
            ) as mock_ingest,
        ):
            self.mock_engine = mock_engine
            self.mock_ingest = mock_ingest
            yield

    def _post_zip(self, client, zip_bytes: bytes, filename: str = "repo.zip"):
        return client.post(
            "/api/v1/repository/upload-and-analyze",
            files={"file": (filename, zip_bytes, "application/zip")},
        )

    def test_valid_zip_returns_200(self, client):
        zip_bytes = _make_zip({"hello.py": "def hello(): pass\n"})
        response = self._post_zip(client, zip_bytes)
        assert response.status_code == 200

    def test_valid_zip_response_shape(self, client):
        zip_bytes = _make_zip({"hello.py": "def hello(): pass\n"})
        data = self._post_zip(client, zip_bytes).json()
        assert "repository_id" in data
        assert "analysis" in data
        assert "ingestion" in data
        assert "message" in data

    def test_valid_zip_analysis_counts(self, client):
        zip_bytes = _make_zip({"hello.py": "def hello(): pass\n"})
        data = self._post_zip(client, zip_bytes).json()
        assert data["analysis"]["total_entities"] == 3
        assert data["ingestion"]["nodes_total"] == 4

    def test_non_zip_file_returns_422(self, client):
        response = self._post_zip(client, b"this is not a zip file")
        assert response.status_code == 422
        assert "ZIP" in response.json()["detail"]

    def test_empty_zip_returns_422(self, client):
        zip_bytes = _make_zip({"readme.txt": "hello"})
        response = self._post_zip(client, zip_bytes)
        assert response.status_code == 422
        assert "No Python files" in response.json()["detail"]

    def test_path_traversal_zip_returns_422(self, client):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../evil.py", "import os")
        response = self._post_zip(client, buf.getvalue())
        assert response.status_code == 422

    def test_neo4j_down_returns_503(self, client_neo4j_down):
        zip_bytes = _make_zip({"hello.py": "def hello(): pass\n"})
        response = self._post_zip(client_neo4j_down, zip_bytes)
        assert response.status_code == 503

    def test_engine_called_once(self, client):
        zip_bytes = _make_zip({"hello.py": "def hello(): pass\n"})
        self._post_zip(client, zip_bytes)
        self.mock_engine.assert_called_once()


# ---------------------------------------------------------------------------
# Graph endpoint tests
# ---------------------------------------------------------------------------

class TestGraphEndpoints:
    """Tests for GET /api/v1/graph/* endpoints."""

    REPO_ID = "repo_abc123"

    @pytest.fixture(autouse=True)
    def mock_queries(self):
        """Mock all Neo4j query functions — no real graph needed."""
        with (
            patch("cypher.api.v1.graph.queries.get_repository_overview",
                  return_value={"total_modules": 5, "total_classes": 2,
                                "total_functions": 10, "total_externals": 3,
                                "total_calls": 15, "total_routes": 4}) as mock_overview,
            patch("cypher.api.v1.graph.queries.find_all_routes",
                  return_value=[{"source": "users.urls", "route": "users/",
                                 "http_methods": ["GET"], "url_name": "user_list",
                                 "handler": "users.views.user_list", "file": "users/views.py"}]) as mock_routes,
            patch("cypher.api.v1.graph.queries.find_function_dependencies",
                  return_value=[{"target": "users.repository.list_users",
                                 "kind": "Function", "file": "users/repository.py", "depth": 1}]) as mock_deps,
            patch("cypher.api.v1.graph.queries.find_function_callers",
                  return_value=[{"caller": "users.views.user_list",
                                 "file": "users/views.py", "depth": 1}]) as mock_callers,
            patch("cypher.api.v1.graph.queries.find_module_dependencies",
                  return_value={"imports": [], "imported_by": []}) as mock_moddeps,
            patch("cypher.api.v1.graph.queries.find_class_hierarchy",
                  return_value=[{"class": "users.models.User", "superclasses": ["django.db.models.Model"],
                                 "subclasses": []}]) as mock_hier,
            patch("cypher.api.v1.graph.queries.find_uncalled_functions",
                  return_value=[{"unused_function": "utils.old_helper",
                                 "file": "utils.py", "line": 42}]) as mock_dead,
        ):
            self.mocks = {
                "overview": mock_overview, "routes": mock_routes,
                "deps": mock_deps, "callers": mock_callers,
                "moddeps": mock_moddeps, "hier": mock_hier, "dead": mock_dead,
            }
            yield

    # -- Overview --

    def test_overview_returns_200(self, client):
        r = client.get(f"/api/v1/graph/overview?repository_id={self.REPO_ID}")
        assert r.status_code == 200

    def test_overview_response_shape(self, client):
        data = client.get(f"/api/v1/graph/overview?repository_id={self.REPO_ID}").json()
        assert data["total_modules"] == 5
        assert data["total_functions"] == 10
        assert data["total_routes"] == 4
        assert data["repository_id"] == self.REPO_ID

    def test_overview_missing_repo_id_returns_422(self, client):
        r = client.get("/api/v1/graph/overview")
        assert r.status_code == 422

    # -- Routes --

    def test_routes_returns_list(self, client):
        data = client.get(f"/api/v1/graph/routes?repository_id={self.REPO_ID}").json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["handler"] == "users.views.user_list"
        assert data[0]["route"] == "users/"

    # -- Function dependencies --

    def test_function_dependencies(self, client):
        data = client.get(
            f"/api/v1/graph/function/users.services.list_users/dependencies"
            f"?repository_id={self.REPO_ID}"
        ).json()
        assert len(data) == 1
        assert data[0]["target"] == "users.repository.list_users"
        assert data[0]["depth"] == 1

    # -- Function callers --

    def test_function_callers(self, client):
        data = client.get(
            f"/api/v1/graph/function/users.services.list_users/callers"
            f"?repository_id={self.REPO_ID}"
        ).json()
        assert len(data) == 1
        assert data[0]["caller"] == "users.views.user_list"

    # -- Module dependencies --

    def test_module_dependencies(self, client):
        data = client.get(
            f"/api/v1/graph/module/users.services/dependencies"
            f"?repository_id={self.REPO_ID}"
        ).json()
        assert "imports" in data
        assert "imported_by" in data
        assert data["module_name"] == "users.services"

    # -- Class hierarchy --

    def test_class_hierarchy(self, client):
        data = client.get(
            f"/api/v1/graph/class/users.models.User/hierarchy"
            f"?repository_id={self.REPO_ID}"
        ).json()
        assert data["class_name"] == "users.models.User"
        assert "django.db.models.Model" in data["superclasses"]

    # -- Dead code --

    def test_dead_code_returns_list(self, client):
        data = client.get(f"/api/v1/graph/dead-code?repository_id={self.REPO_ID}").json()
        assert isinstance(data, list)
        assert data[0]["unused_function"] == "utils.old_helper"
        assert data[0]["line"] == 42

    # -- Neo4j down --

    def test_graph_endpoints_503_when_neo4j_down(self, client_neo4j_down):
        r = client_neo4j_down.get(f"/api/v1/graph/overview?repository_id={self.REPO_ID}")
        assert r.status_code == 503
