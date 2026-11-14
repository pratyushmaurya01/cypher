"""Tests for Phase 2: Database Migrations (Alembic) and Repository Deletion Lifecycle."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from alembic import command
from alembic.config import Config
from cypher.config import get_settings
from cypher.core.security import create_access_token, hash_password
from cypher.db.models import Base, RepositoryMetadata, User
from cypher.db.session import get_db
from cypher.main import create_app
from cypher.services.source_code_service import SourceCodeService


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content.encode("utf-8"))
    return buf.getvalue()


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
def client_and_users(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session

    mock_neo4j = MagicMock()
    mock_neo4j.verify_connectivity.return_value = True
    mock_neo4j.execute_write.return_value = None
    mock_neo4j.execute_batch.return_value = None
    mock_neo4j.execute_query.return_value = []

    user_a = User(
        email="p2_user_a@example.com",
        hashed_password=hash_password("Pass1234"),
        is_active=True,
    )
    user_b = User(
        email="p2_user_b@example.com",
        hashed_password=hash_password("Pass1234"),
        is_active=True,
    )
    db_session.add_all([user_a, user_b])
    db_session.commit()
    db_session.refresh(user_a)
    db_session.refresh(user_b)

    token_a = create_access_token(subject=user_a.id, extra_claims={"email": user_a.email})
    token_b = create_access_token(subject=user_b.id, extra_claims={"email": user_b.email})

    with TestClient(app, raise_server_exceptions=True) as tc:
        tc.app.state.neo4j_client = mock_neo4j
        yield tc, user_a, user_b, {"Authorization": f"Bearer {token_a}"}, {"Authorization": f"Bearer {token_b}"}


class TestPhase2LifecycleAndMigrations:
    """Verifies Alembic migrations and atomic repository deletion across DB, Neo4j, and Disk."""

    def test_alembic_upgrade_downgrade_cycle(self, tmp_path):
        """Alembic migrations run cleanly up and down on a real file-based SQLite database."""
        test_db_path = tmp_path / "alembic_test.db"
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{test_db_path}")

        # Upgrade to head
        command.upgrade(alembic_cfg, "head")
        assert test_db_path.exists()

        # Downgrade to base
        command.downgrade(alembic_cfg, "base")

        # Re-upgrade to head
        command.upgrade(alembic_cfg, "head")

    def test_repository_deletion_success_removes_db_neo4j_and_disk(
        self, client_and_users, db_session
    ):
        """DELETE /api/v1/repository/{repository_id} cascades across DB, Neo4j and filesystem."""
        client, user_a, _, headers_a, _ = client_and_users

        zip_bytes = _make_zip({"module.py": "def f(): pass\n"})
        res_upload = client.post(
            "/api/v1/repository/upload-and-analyze",
            files={"file": ("to_delete.zip", zip_bytes, "application/zip")},
            headers=headers_a,
        )
        assert res_upload.status_code == 200
        repo_id = res_upload.json()["repository_id"]

        # Verify exists in DB and on disk
        repo_record = db_session.query(RepositoryMetadata).filter_by(repository_id=repo_id).first()
        assert repo_record is not None
        source_service = SourceCodeService()
        repo_disk_path = source_service.storage_dir / str(user_a.id) / repo_id
        assert repo_disk_path.exists()

        # Execute DELETE
        res_del = client.delete(f"/api/v1/repository/{repo_id}", headers=headers_a)
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "deleted"

        # Verify DB record is removed
        repo_after = db_session.query(RepositoryMetadata).filter_by(repository_id=repo_id).first()
        assert repo_after is None

        # Verify filesystem storage is removed
        assert not repo_disk_path.exists()

        # Verify Neo4j delete query was invoked
        mock_neo4j = client.app.state.neo4j_client
        mock_neo4j.execute_write.assert_called()

    def test_cross_user_deletion_forbidden(self, client_and_users, db_session):
        """User B cannot delete User A's repository."""
        client, user_a, user_b, headers_a, headers_b = client_and_users

        zip_bytes = _make_zip({"safe.py": "def safe(): pass\n"})
        res_upload = client.post(
            "/api/v1/repository/upload-and-analyze",
            files={"file": ("protected.zip", zip_bytes, "application/zip")},
            headers=headers_a,
        )
        assert res_upload.status_code == 200
        repo_id = res_upload.json()["repository_id"]

        # User B attempts to delete User A's repository
        res_del = client.delete(f"/api/v1/repository/{repo_id}", headers=headers_b)
        assert res_del.status_code == 403

        # Repository must still exist in DB
        repo_record = db_session.query(RepositoryMetadata).filter_by(repository_id=repo_id).first()
        assert repo_record is not None
