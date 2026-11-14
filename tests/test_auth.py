"""Tests for PostgreSQL database integration, user authentication, and repository ownership isolation."""

from __future__ import annotations

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cypher.db.models import Base, RepositoryMetadata, User
from cypher.db.session import get_db
from cypher.main import create_app


# ---------------------------------------------------------------------------
# Test Fixtures with In-Memory Database
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    """Create an isolated in-memory SQLite database for the test."""
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
def client(db_session):
    """TestClient that uses the isolated in-memory DB and mocked Neo4j."""
    app = create_app()

    # Override get_db dependency with test session
    app.dependency_overrides[get_db] = lambda: db_session

    mock_neo4j = MagicMock()
    mock_neo4j.verify_connectivity.return_value = True

    with TestClient(app, raise_server_exceptions=True) as test_client:
        test_client.app.state.neo4j_client = mock_neo4j
        yield test_client
    app.dependency_overrides.clear()


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Signup Tests
# ---------------------------------------------------------------------------

class TestSignup:
    def test_signup_success(self, client, db_session):
        res = client.post(
            "/api/v1/auth/signup",
            json={"email": "alice@example.com", "password": "password123"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["email"] == "alice@example.com"
        assert "id" in data
        assert data["is_active"] is True

        # Verify plaintext password was NOT stored in database
        user = db_session.query(User).filter(User.email == "alice@example.com").first()
        assert user is not None
        assert user.hashed_password != "password123"
        assert user.hashed_password.startswith("$2b$")

    def test_signup_duplicate_email_fails(self, client):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "alice@example.com", "password": "password123"},
        )
        res = client.post(
            "/api/v1/auth/signup",
            json={"email": "alice@example.com", "password": "anotherpassword"},
        )
        assert res.status_code == 400
        assert "already exists" in res.json()["detail"]

    def test_signup_invalid_email_fails(self, client):
        res = client.post(
            "/api/v1/auth/signup",
            json={"email": "not-an-email", "password": "password123"},
        )
        assert res.status_code == 422

    def test_signup_short_password_fails(self, client):
        res = client.post(
            "/api/v1/auth/signup",
            json={"email": "short@example.com", "password": "123"},
        )
        assert res.status_code == 422


# ---------------------------------------------------------------------------
# 2. Login Tests
# ---------------------------------------------------------------------------

class TestLogin:
    @pytest.fixture(autouse=True)
    def setup_user(self, client):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "bob@example.com", "password": "securepassword"},
        )

    def test_login_success(self, client):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "bob@example.com", "password": "securepassword"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password_fails(self, client):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "bob@example.com", "password": "wrongpassword"},
        )
        assert res.status_code == 401
        assert "Incorrect email or password" in res.json()["detail"]

    def test_login_nonexistent_user_fails(self, client):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "anypassword"},
        )
        assert res.status_code == 401


# ---------------------------------------------------------------------------
# 3. Protected Profile (/auth/me) Tests
# ---------------------------------------------------------------------------

class TestUserProfile:
    def test_me_without_token_fails(self, client):
        res = client.get("/api/v1/auth/me")
        assert res.status_code == 401

    def test_me_with_invalid_token_fails(self, client):
        res = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token.payload"},
        )
        assert res.status_code == 401

    def test_me_with_valid_token_success(self, client):
        client.post(
            "/api/v1/auth/signup",
            json={"email": "carol@example.com", "password": "carolpassword"},
        )
        token_res = client.post(
            "/api/v1/auth/login",
            json={"email": "carol@example.com", "password": "carolpassword"},
        )
        token = token_res.json()["access_token"]

        res = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "carol@example.com"
        assert "id" in data


# ---------------------------------------------------------------------------
# 4. Repository Ownership & Cross-User Isolation Tests
# ---------------------------------------------------------------------------

class TestRepositoryOwnershipAndIsolation:
    """Verify authenticated repository ownership and cross-user isolation."""

    @pytest.fixture(autouse=True)
    def setup_users(self, client):
        # Register User A
        client.post(
            "/api/v1/auth/signup",
            json={"email": "usera@example.com", "password": "passwordA123"},
        )
        tok_a = client.post(
            "/api/v1/auth/login",
            json={"email": "usera@example.com", "password": "passwordA123"},
        ).json()["access_token"]
        self.headers_a = {"Authorization": f"Bearer {tok_a}"}

        # Register User B
        client.post(
            "/api/v1/auth/signup",
            json={"email": "userb@example.com", "password": "passwordB123"},
        )
        tok_b = client.post(
            "/api/v1/auth/login",
            json={"email": "userb@example.com", "password": "passwordB123"},
        ).json()["access_token"]
        self.headers_b = {"Authorization": f"Bearer {tok_b}"}

    def test_upload_records_ownership_in_db(self, client, db_session):
        fake_analysis = {
            "repository": {"root": "/tmp/repo_a", "files_count": 1},
            "entities": [],
            "relationships": [],
            "unresolved_references": [],
            "diagnostics": [],
            "stats": {"total_entities": 1, "entities_by_kind": {}, "total_relationships": 0, "relationships_by_type": {}},
        }
        fake_ingestion = {
            "dry_run": False,
            "repository_id": "repo_user_a_1",
            "nodes_total": 2,
            "nodes_by_label": {},
            "relationships_total": 1,
            "relationships_by_type": {},
        }

        with (
            patch("cypher.services.analysis_service.analyze_repository", return_value=fake_analysis),
            patch("cypher.services.analysis_service.GraphBuilder.ingest", return_value=fake_ingestion),
        ):
            zip_bytes = _make_zip({"main.py": "def main(): pass\n"})
            res = client.post(
                "/api/v1/repository/upload-and-analyze",
                files={"file": ("project.zip", zip_bytes, "application/zip")},
                headers=self.headers_a,
            )
            assert res.status_code == 200
            assert res.json()["repository_id"] == "repo_user_a_1"

        # Verify database record
        user_a = db_session.query(User).filter(User.email == "usera@example.com").first()
        repo = db_session.query(RepositoryMetadata).filter(RepositoryMetadata.repository_id == "repo_user_a_1").first()
        assert repo is not None
        assert repo.owner_id == user_a.id
        assert repo.status == "analyzed"

    def test_list_my_repositories_isolation(self, client, db_session):
        user_a = db_session.query(User).filter(User.email == "usera@example.com").first()
        user_b = db_session.query(User).filter(User.email == "userb@example.com").first()

        db_session.add(RepositoryMetadata(repository_id="repo_a_private", owner_id=user_a.id, name="Project A", status="analyzed"))
        db_session.add(RepositoryMetadata(repository_id="repo_b_private", owner_id=user_b.id, name="Project B", status="analyzed"))
        db_session.commit()

        # User A only sees repo_a_private
        res_a = client.get("/api/v1/repository/my-repositories", headers=self.headers_a)
        assert res_a.status_code == 200
        ids_a = [r["repository_id"] for r in res_a.json()]
        assert "repo_a_private" in ids_a
        assert "repo_b_private" not in ids_a

        # User B only sees repo_b_private
        res_b = client.get("/api/v1/repository/my-repositories", headers=self.headers_b)
        assert res_b.status_code == 200
        ids_b = [r["repository_id"] for r in res_b.json()]
        assert "repo_b_private" in ids_b
        assert "repo_a_private" not in ids_b

    def test_get_repository_details_access_control(self, client, db_session):
        user_a = db_session.query(User).filter(User.email == "usera@example.com").first()
        db_session.add(RepositoryMetadata(repository_id="repo_a_secret", owner_id=user_a.id, name="Secret Repo", status="analyzed"))
        db_session.commit()

        # Owner (User A) can access details
        res_owner = client.get("/api/v1/repository/repo_a_secret", headers=self.headers_a)
        assert res_owner.status_code == 200
        assert res_owner.json()["name"] == "Secret Repo"

        # Non-owner (User B) is forbidden (403)
        res_intruder = client.get("/api/v1/repository/repo_a_secret", headers=self.headers_b)
        assert res_intruder.status_code == 403
        assert "do not have access" in res_intruder.json()["detail"]

    def test_cross_user_graph_data_isolation(self, client, db_session):
        """User B cannot query graph endpoints for User A's repository."""
        user_a = db_session.query(User).filter(User.email == "usera@example.com").first()
        db_session.add(RepositoryMetadata(repository_id="repo_a_confidential", owner_id=user_a.id, name="Confidential", status="analyzed"))
        db_session.commit()

        with patch("cypher.api.v1.graph.queries.get_repository_overview", return_value={"total_modules": 5, "total_classes": 1, "total_functions": 2, "total_externals": 0, "total_calls": 3, "total_routes": 1}):
            # 1. User A (Owner) queries graph overview -> 200 OK
            res_owner = client.get("/api/v1/graph/overview?repository_id=repo_a_confidential", headers=self.headers_a)
            assert res_owner.status_code == 200
            assert res_owner.json()["total_modules"] == 5

            # 2. User B (Another User) queries graph overview -> 403 Forbidden!
            res_intruder = client.get("/api/v1/graph/overview?repository_id=repo_a_confidential", headers=self.headers_b)
            assert res_intruder.status_code == 403
            assert "do not have access" in res_intruder.json()["detail"]

            # 3. Unauthenticated request queries graph overview -> 401 Unauthorized!
            res_unauth = client.get("/api/v1/graph/overview?repository_id=repo_a_confidential")
            assert res_unauth.status_code == 401

    def test_user_cannot_hijack_another_users_repository_id(self, client, db_session):
        """User B cannot upload a repository that collides with User A's repository."""
        user_a = db_session.query(User).filter(User.email == "usera@example.com").first()
        db_session.add(RepositoryMetadata(repository_id="repo_unique_id", owner_id=user_a.id, name="User A Repo", status="analyzed"))
        db_session.commit()

        fake_analysis = {"repository": {"root": "/tmp/r", "files_count": 1}, "entities": [], "relationships": [], "unresolved_references": [], "diagnostics": [], "stats": {}}
        fake_ingestion = {"dry_run": False, "repository_id": "repo_unique_id", "nodes_total": 1, "nodes_by_label": {}, "relationships_total": 0, "relationships_by_type": {}}

        with (
            patch("cypher.services.analysis_service.analyze_repository", return_value=fake_analysis),
            patch("cypher.services.analysis_service.GraphBuilder.ingest", return_value=fake_ingestion),
        ):
            zip_bytes = _make_zip({"app.py": "pass\n"})
            # User B attempts to upload with same repository_id
            res = client.post(
                "/api/v1/repository/upload-and-analyze",
                files={"file": ("project.zip", zip_bytes, "application/zip")},
                headers=self.headers_b,
            )
            assert res.status_code == 403
            assert "already owned by another account" in res.json()["detail"]
