"""Tests for Phase 1: Upload Security, Streaming, ZIP Bomb Protection, and Atomic Staging."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cypher.config import get_settings
from cypher.core.security import create_access_token, hash_password
from cypher.db.models import Base, RepositoryMetadata, User
from cypher.db.session import get_db
from cypher.main import create_app
from cypher.services.analysis_service import (
    MAX_ARCHIVE_FILE_COUNT,
    MAX_UNCOMPRESSED_SIZE_BYTES,
    PathTraversalError,
    SuspiciousArchiveError,
    extract_zip,
)
from cypher.services.source_code_service import SourceCodeService


def _make_zip(files: dict[str, str | bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=compression) as zf:
        for name, content in files.items():
            if isinstance(content, str):
                zf.writestr(name, content.encode("utf-8"))
            else:
                zf.writestr(name, content)
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
def client_with_user(db_session):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db_session

    mock_neo4j = MagicMock()
    mock_neo4j.verify_connectivity.return_value = True
    mock_neo4j.execute_write.return_value = None
    mock_neo4j.execute_batch.return_value = None
    mock_neo4j.execute_query.return_value = []

    user = User(
        email="phase1_user@example.com",
        hashed_password=hash_password("Pass1234"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = create_access_token(subject=user.id, extra_claims={"email": user.email})
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app, raise_server_exceptions=True) as tc:
        tc.app.state.neo4j_client = mock_neo4j
        yield tc, user, headers


class TestPhase1UploadSecurityAndStaging:
    """Verifies chunked streaming limits, ZIP bomb detection, and atomic staging rollback."""

    def test_streaming_upload_limit_rejected_at_threshold(self, client_with_user, monkeypatch):
        """Streaming reader aborts immediately when payload exceeds max_upload_bytes."""
        client, _, headers = client_with_user
        settings = get_settings()
        monkeypatch.setattr(settings, "max_upload_bytes", 200)

        # Upload exceeds 200 bytes
        big_content = "def test():\n    return 'This is a long string that will not compress away' * 10\n" * 20
        zip_bytes = _make_zip({"overflow.py": big_content})
        assert len(zip_bytes) > 200

        res = client.post(
            "/api/v1/repository/upload-and-analyze",
            files={"file": ("overflow.zip", zip_bytes, "application/zip")},
            headers=headers,
        )
        assert res.status_code == 413
        assert "Upload exceeds the maximum allowed size" in res.json()["detail"]

    def test_zip_bomb_uncompressed_size_rejected(self, tmp_path):
        """Archive with uncompressed content exceeding threshold raises SuspiciousArchiveError."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        # Simulate uncompressed size check by mocking MAX_UNCOMPRESSED_SIZE_BYTES
        zip_bytes = _make_zip({"file.py": "a" * 1000})

        with patch("cypher.services.analysis_service.MAX_UNCOMPRESSED_SIZE_BYTES", 500):
            with pytest.raises(SuspiciousArchiveError) as exc_info:
                extract_zip(zip_bytes, max_bytes=10000, work_dir=work_dir)
            assert "Total uncompressed archive size exceeds" in str(exc_info.value)

    def test_zip_bomb_extreme_compression_ratio_rejected(self, tmp_path):
        """Archive entry with compression ratio > 100x raises SuspiciousArchiveError."""
        work_dir = tmp_path / "work_ratio"
        work_dir.mkdir()

        # High-repetition string creates extreme compression ratio
        highly_compressible = "0" * (100 * 1024)  # 100 KB of zeroes
        zip_bytes = _make_zip({"zeroes.py": highly_compressible})

        with pytest.raises(SuspiciousArchiveError) as exc_info:
            extract_zip(zip_bytes, max_bytes=10 * 1024 * 1024, work_dir=work_dir)
        assert "excessive compression ratio" in str(exc_info.value)

    def test_nested_archive_rejected(self, tmp_path):
        """Archives containing nested .zip files are rejected."""
        work_dir = tmp_path / "work_nested"
        work_dir.mkdir()

        inner_zip = _make_zip({"inner.py": "pass\n"})
        outer_zip = _make_zip({"inner.zip": inner_zip, "app.py": "pass\n"})

        with pytest.raises(SuspiciousArchiveError) as exc_info:
            extract_zip(outer_zip, max_bytes=10 * 1024 * 1024, work_dir=work_dir)
        assert "Nested archive detected" in str(exc_info.value)

    def test_atomic_staging_rollback_on_analysis_failure(self, client_with_user, tmp_path):
        """When analysis or Neo4j ingestion fails, unpromoted staging files are cleaned up."""
        client, user, headers = client_with_user

        zip_bytes = _make_zip({"broken.py": "def broken(): pass\n"})

        with patch("cypher.api.v1.repository.run_analysis", side_effect=RuntimeError("Simulated Neo4j crash")):
            res = client.post(
                "/api/v1/repository/upload-and-analyze",
                files={"file": ("crash.zip", zip_bytes, "application/zip")},
                headers=headers,
            )
            assert res.status_code == 500

        # Check repository storage directory: no orphaned staging directories should remain
        settings = get_settings()
        repo_storage = Path(settings.storage_dir) / str(user.id)
        if repo_storage.exists():
            for repo_dir in repo_storage.iterdir():
                if repo_dir.is_dir():
                    staging_dirs = [d.name for d in repo_dir.iterdir() if d.name.startswith(".staging_")]
                    assert staging_dirs == [], f"Found uncleaned staging dirs: {staging_dirs}"
