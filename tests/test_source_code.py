"""Tests for Stage 4: SourceCodeService, snapshot storage, line range extraction, and source retrieval APIs."""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cypher.db.models import Base, RepositoryMetadata, User
from cypher.db.session import get_db
from cypher.main import create_app
from cypher.services.source_code_service import (
    InvalidLineRangeError,
    PathTraversalError,
    RepositoryNotFoundError,
    SourceCodeService,
    SourceFileNotFoundError,
    SymbolNotFoundError,
)

SAMPLE_CODE = '''# Module docstring
"""A sample module demonstrating exact code preservation."""

import os
from typing import List


def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    # Indented calculation comment
    result = a + b
    return result


class Calculator:
    """Calculator service."""

    def __init__(self, offset: int = 0):
        self.offset = offset

    def calculate(self, x: int) -> int:
        return x + self.offset
'''

TOTAL_LINES = len(SAMPLE_CODE.splitlines())


# ---------------------------------------------------------------------------
# Unit Tests for SourceCodeService
# ---------------------------------------------------------------------------

class TestSourceCodeServiceUnit:
    @pytest.fixture()
    def storage_env(self, tmp_path):
        """Create a temporary storage environment and sample source directory."""
        source_dir = tmp_path / "sample_source"
        source_dir.mkdir()
        (source_dir / "calculator.py").write_bytes(SAMPLE_CODE.encode("utf-8"))
        (source_dir / "utils.py").write_bytes(b"def helper():\n    return True\n")

        # Nested folder
        (source_dir / "pkg").mkdir()
        (source_dir / "pkg" / "nested.py").write_bytes(b"# nested\nVALUE = 42\n")

        storage_root = tmp_path / "storage"
        service = SourceCodeService(storage_dir=storage_root)
        return service, source_dir, storage_root

    def test_store_and_retrieve_snapshot(self, storage_env):
        service, source_dir, storage_root = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        assert dest.exists()
        assert (dest / "calculator.py").exists()
        assert (dest / "pkg" / "nested.py").exists()

        # Retrieve file content
        file_info = service.get_file_content(dest, "calculator.py")
        assert file_info["file_path"] == "calculator.py"
        assert file_info["total_lines"] == TOTAL_LINES
        assert file_info["encoding"] == "utf-8"
        assert file_info["content"] == SAMPLE_CODE

    def test_exact_whitespace_and_comments_preserved(self, storage_env):
        service, source_dir, _ = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        range_info = service.get_line_range(dest, "calculator.py", start_line=8, end_line=13)
        expected_lines = [
            'def add_numbers(a: int, b: int) -> int:\n',
            '    """Add two numbers together."""\n',
            '    # Indented calculation comment\n',
            '    result = a + b\n',
            '    return result\n',
            '\n',
        ]
        assert range_info["content"] == "".join(expected_lines)
        assert range_info["start_line"] == 8
        assert range_info["end_line"] == 13

    def test_invalid_line_ranges(self, storage_env):
        service, source_dir, _ = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        with pytest.raises(InvalidLineRangeError):
            service.get_line_range(dest, "calculator.py", start_line=0)

        with pytest.raises(InvalidLineRangeError):
            service.get_line_range(dest, "calculator.py", start_line=10, end_line=5)

        with pytest.raises(InvalidLineRangeError):
            service.get_line_range(dest, "calculator.py", start_line=999)

    def test_path_traversal_prevention(self, storage_env):
        service, source_dir, _ = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        with pytest.raises(PathTraversalError):
            service.get_file_content(dest, "../../etc/passwd")

        with pytest.raises(PathTraversalError):
            service.get_file_content(dest, "..\\..\\windows\\system32")

    def test_non_existent_file_raises_error(self, storage_env):
        service, source_dir, _ = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        with pytest.raises(SourceFileNotFoundError):
            service.get_file_content(dest, "does_not_exist.py")

    def test_symbol_extraction_via_ast(self, storage_env):
        service, source_dir, _ = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        # Function symbol
        fn_symbol = service.get_symbol_source(dest, "add_numbers")
        assert fn_symbol["name"] == "add_numbers"
        assert fn_symbol["kind"] == "function"
        assert "def add_numbers(a: int, b: int) -> int:" in fn_symbol["source_code"]
        assert "result = a + b" in fn_symbol["source_code"]

        # Class symbol
        cls_symbol = service.get_symbol_source(dest, "Calculator")
        assert cls_symbol["name"] == "Calculator"
        assert cls_symbol["kind"] == "class"
        assert "class Calculator:" in cls_symbol["source_code"]
        assert "def calculate(self, x: int) -> int:" in cls_symbol["source_code"]

    def test_symbol_extraction_via_neo4j_metadata(self, storage_env):
        service, source_dir, _ = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        mock_neo4j = MagicMock()
        mock_neo4j.execute_query.return_value = [
            {
                "file_path": "calculator.py",
                "line": 8,
                "end_line": 12,
                "name": "add_numbers",
                "kind": "Function",
            }
        ]

        sym = service.get_symbol_source(
            dest,
            "sample.add_numbers",
            neo4j_client=mock_neo4j,
            repository_id="repo_123",
        )
        assert sym["start_line"] == 8
        assert sym["end_line"] == 12
        assert "def add_numbers" in sym["source_code"]

    def test_missing_symbol_raises_error(self, storage_env):
        service, source_dir, _ = storage_env
        dest = service.store_snapshot(source_dir, owner_id=1, repository_id="repo_123")

        with pytest.raises(SymbolNotFoundError):
            service.get_symbol_source(dest, "nonexistent_function")


# ---------------------------------------------------------------------------
# API Integration Tests for Source Endpoints (/api/v1/source/*)
# ---------------------------------------------------------------------------

class TestSourceCodeAPI:
    @pytest.fixture()
    def api_env(self, tmp_path):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        session = TestingSessionLocal()

        app = create_app()
        app.dependency_overrides[get_db] = lambda: session

        mock_neo4j = MagicMock()
        mock_neo4j.verify_connectivity.return_value = True
        mock_neo4j.execute_query.return_value = []

        client = TestClient(app, raise_server_exceptions=True)
        client.app.state.neo4j_client = mock_neo4j

        # Register User 1 & User 2
        client.post("/api/v1/auth/signup", json={"email": "u1@example.com", "password": "password123"})
        tok_1 = client.post("/api/v1/auth/login", json={"email": "u1@example.com", "password": "password123"}).json()["access_token"]
        headers_1 = {"Authorization": f"Bearer {tok_1}"}

        client.post("/api/v1/auth/signup", json={"email": "u2@example.com", "password": "password456"})
        tok_2 = client.post("/api/v1/auth/login", json={"email": "u2@example.com", "password": "password456"}).json()["access_token"]
        headers_2 = {"Authorization": f"Bearer {tok_2}"}

        # Create persistent snapshot on disk for User 1's repo
        u1_user = session.query(User).filter(User.email == "u1@example.com").first()
        repo_dir = tmp_path / "storage" / str(u1_user.id) / "repo_test_1"
        repo_dir.mkdir(parents=True)
        (repo_dir / "app.py").write_bytes(SAMPLE_CODE.encode("utf-8"))

        # Add repository metadata in DB
        repo = RepositoryMetadata(
            repository_id="repo_test_1",
            owner_id=u1_user.id,
            name="Test App",
            storage_path=str(repo_dir),
            status="analyzed",
        )
        session.add(repo)
        session.commit()

        yield {
            "client": client,
            "headers_1": headers_1,
            "headers_2": headers_2,
            "repo_id": "repo_test_1",
        }

        session.close()
        Base.metadata.drop_all(bind=engine)
        app.dependency_overrides.clear()

    def test_get_file_owner_success(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/file?path=app.py",
            headers=api_env["headers_1"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["file_path"] == "app.py"
        assert data["total_lines"] == TOTAL_LINES
        assert "class Calculator:" in data["content"]

    def test_get_file_unauthenticated_fails(self, api_env):
        client = api_env["client"]
        res = client.get(f"/api/v1/source/{api_env['repo_id']}/file?path=app.py")
        assert res.status_code == 401

    def test_get_file_other_user_forbidden(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/file?path=app.py",
            headers=api_env["headers_2"],  # User 2 attempting to view User 1's file
        )
        assert res.status_code == 403
        assert "do not have access" in res.json()["detail"]

    def test_get_file_path_traversal_fails(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/file?path=../../secret.txt",
            headers=api_env["headers_1"],
        )
        assert res.status_code == 400
        assert "traversal" in res.json()["detail"].lower()

    def test_get_file_missing_file_fails(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/file?path=nonexistent.py",
            headers=api_env["headers_1"],
        )
        assert res.status_code == 404

    def test_get_line_range_success(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/range?path=app.py&start_line=8&end_line=12",
            headers=api_env["headers_1"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["start_line"] == 8
        assert data["end_line"] == 12
        assert "def add_numbers(a: int, b: int) -> int:" in data["content"]
        assert len(data["lines"]) == 5

    def test_get_line_range_invalid_parameters_fails(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/range?path=app.py&start_line=15&end_line=5",
            headers=api_env["headers_1"],
        )
        assert res.status_code == 400

    def test_get_symbol_success(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/symbol?name=Calculator",
            headers=api_env["headers_1"],
        )
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Calculator"
        assert data["kind"] == "class"
        assert "class Calculator:" in data["source_code"]
        assert "def calculate" in data["source_code"]

    def test_get_symbol_not_found(self, api_env):
        client = api_env["client"]
        res = client.get(
            f"/api/v1/source/{api_env['repo_id']}/symbol?name=MissingSymbol",
            headers=api_env["headers_1"],
        )
        assert res.status_code == 404
