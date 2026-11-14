"""Source code retrieval endpoints — access verified source files, line ranges, and symbols.

GET /api/v1/source/{repository_id}/file?path=...
    Retrieve full file content with encoding detection.

GET /api/v1/source/{repository_id}/range?path=...&start_line=...&end_line=...
    Retrieve a specific range of lines preserving exact indentation and comments.

GET /api/v1/source/{repository_id}/symbol?name=...
    Retrieve exact function or class definition source code using AST / graph metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from cypher.api.deps import get_current_user, verify_repository_access
from cypher.db.models import User
from cypher.db.session import get_db
from cypher.schemas.source import (
    CodeRangeResponse,
    FileContentResponse,
    SymbolSourceResponse,
)
from cypher.services.source_code_service import (
    InvalidLineRangeError,
    PathTraversalError,
    RepositoryNotFoundError,
    SourceCodeService,
    SourceFileNotFoundError,
    SymbolNotFoundError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/source", tags=["Source Code"])


def _get_snapshot_directory(
    repository_id: str,
    current_user: User,
    db: Session,
    service: SourceCodeService,
) -> Path:
    """Verify repository ownership and resolve persistent snapshot directory."""
    repo = verify_repository_access(repository_id, current_user, db)

    if repo.storage_path and Path(repo.storage_path).exists():
        return Path(repo.storage_path)

    snapshot_dir = service.get_snapshot_path(repo.owner_id, repo.repository_id)
    if not snapshot_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source snapshot for repository '{repository_id}' is not available.",
        )
    return snapshot_dir


@router.get(
    "/{repository_id}/file",
    response_model=FileContentResponse,
    summary="Retrieve full source file content",
)
def get_file(
    repository_id: str,
    path: Annotated[str, Query(description="Relative file path within repository (e.g. users/views.py)")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> FileContentResponse:
    """Retrieve the complete source text of a file from the repository snapshot.

    Exact indentation, comments, and line breaks are preserved.
    """
    service = SourceCodeService()
    snapshot_dir = _get_snapshot_directory(repository_id, current_user, db, service)

    try:
        res = service.get_file_content(snapshot_dir, path)
    except PathTraversalError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (SourceFileNotFoundError, RepositoryNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return FileContentResponse(
        repository_id=repository_id,
        file_path=res["file_path"],
        content=res["content"],
        total_lines=res["total_lines"],
        size_bytes=res["size_bytes"],
        encoding=res["encoding"],
    )


@router.get(
    "/{repository_id}/range",
    response_model=CodeRangeResponse,
    summary="Retrieve a specific line range from a source file",
)
def get_range(
    repository_id: str,
    path: Annotated[str, Query(description="Relative file path within repository")],
    start_line: Annotated[int, Query(ge=1, description="1-indexed starting line number")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    end_line: Annotated[int | None, Query(ge=1, description="1-indexed ending line number (optional)")] = None,
) -> CodeRangeResponse:
    """Extract a range of lines from a source file.

    Guarantees no modifications to original code formatting or indentation.
    """
    service = SourceCodeService()
    snapshot_dir = _get_snapshot_directory(repository_id, current_user, db, service)

    try:
        res = service.get_line_range(snapshot_dir, path, start_line, end_line)
    except PathTraversalError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (SourceFileNotFoundError, RepositoryNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidLineRangeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return CodeRangeResponse(
        repository_id=repository_id,
        file_path=res["file_path"],
        start_line=res["start_line"],
        end_line=res["end_line"],
        total_lines=res["total_lines"],
        content=res["content"],
        lines=res["lines"],
    )


@router.get(
    "/{repository_id}/symbol",
    response_model=SymbolSourceResponse,
    summary="Retrieve exact source definition of a function or class",
)
def get_symbol(
    request: Request,
    repository_id: str,
    name: Annotated[str, Query(description="Qualified symbol name (e.g. users.services.create_user or User)")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SymbolSourceResponse:
    """Retrieve the exact source code definition of a function or class.

    Uses AST line boundaries and knowledge graph metadata.
    """
    service = SourceCodeService()
    snapshot_dir = _get_snapshot_directory(repository_id, current_user, db, service)
    neo4j_client = getattr(request.app.state, "neo4j_client", None)

    try:
        res = service.get_symbol_source(
            snapshot_dir,
            name,
            neo4j_client=neo4j_client,
            repository_id=repository_id,
        )
    except SymbolNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PathTraversalError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (SourceFileNotFoundError, RepositoryNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return SymbolSourceResponse(
        repository_id=repository_id,
        qualified_name=res["qualified_name"],
        name=res["name"],
        kind=res["kind"],
        file_path=res["file_path"],
        start_line=res["start_line"],
        end_line=res["end_line"],
        total_file_lines=res["total_file_lines"],
        source_code=res["source_code"],
    )
