"""Repository upload, analysis, and metadata registry endpoints.

POST /api/v1/repository/upload-and-analyze
    Accepts a ZIP file, extracts it, runs the full analysis pipeline,
    writes the resulting graph into Neo4j, and persists ownership metadata in PostgreSQL.

GET /api/v1/repository/my-repositories
    Returns all repositories owned by the currently authenticated user.

GET /api/v1/repository/{repository_id}
    Returns repository metadata with ownership check.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy.orm import Session

from cypher.api.deps import (
    get_current_user,
    get_current_user_optional,
    verify_repository_access,
)
from cypher.config import get_settings
from cypher.core.security import hash_password
from cypher.db.models import RepositoryMetadata, User
from cypher.db.session import get_db
from cypher.schemas.repository import (
    AnalysisResponse,
    AnalysisSummary,
    IngestionSummary,
    RepositoryListItem,
    UploadResponse,
)
from cypher.services.analysis_service import (
    AnalysisServiceError,
    EmptyRepositoryError,
    InvalidZipError,
    PathTraversalError,
    extract_zip,
    run_analysis,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/repository", tags=["Repository"])


def _get_neo4j_client(request: Request):
    """Return the shared Neo4j client, or raise 503 if unavailable."""
    client = getattr(request.app.state, "neo4j_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j is not connected. Check /api/v1/health for details.",
        )
    return client


def _get_or_create_default_dev_user(db: Session) -> User:
    """Retrieve or create an unauthenticated fallback dev user for backwards compatibility."""
    dev_email = "dev-anonymous@cypher.local"
    user = db.query(User).filter(User.email == dev_email).first()
    if user is None:
        user = User(
            email=dev_email,
            hashed_password=hash_password("insecure-dev-password"),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


@router.post(
    "/upload-and-analyze",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload a ZIP archive and analyze the Python repository inside it",
)
async def upload_and_analyze(
    request: Request,
    file: UploadFile,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> AnalysisResponse:
    """Upload a ZIP file containing a Python project, analyze it, store the
    resulting Code Knowledge Graph in Neo4j, and record ownership in PostgreSQL.

    **Steps performed:**
    1. Validate the uploaded file (ZIP format, size limit).
    2. Extract the ZIP safely (preventing path traversal).
    3. Run the AST analysis engine on the extracted code.
    4. Ingest entities and relationships into Neo4j.
    5. Save repository ownership and metadata in PostgreSQL.
    6. Return a summary of what was stored.
    """
    settings = get_settings()
    neo4j_client = _get_neo4j_client(request)

    # Determine acting owner: authenticated user, or fallback dev user
    owner = current_user or _get_or_create_default_dev_user(db)

    # Read file into memory
    zip_bytes = await file.read()

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        try:
            python_root, repo_name, py_count = extract_zip(
                zip_bytes,
                max_bytes=settings.max_upload_bytes,
                work_dir=work_dir,
            )
        except InvalidZipError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
        except PathTraversalError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
        except AnalysisServiceError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=str(exc),
            )

        if py_count == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No Python files found inside the uploaded ZIP.",
            )

        try:
            result = run_analysis(python_root, neo4j_client, clear_existing=True)
            repo_id = result["repository_id"]

            # Persist immutable repository snapshot before temp directory is deleted
            from cypher.services.source_code_service import SourceCodeService
            source_service = SourceCodeService()
            snapshot_path = source_service.store_snapshot(
                source_dir=python_root,
                owner_id=owner.id,
                repository_id=repo_id,
            )
        except Exception as exc:
            logger.error("Analysis failed for '%s': %s", repo_name, exc, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Analysis failed. Check server logs for details."
                if not settings.is_development
                else str(exc),
            )

    repo_id = result["repository_id"]

    # Check if this repository_id was already claimed by another user
    existing_repo = (
        db.query(RepositoryMetadata)
        .filter(RepositoryMetadata.repository_id == repo_id)
        .first()
    )
    if existing_repo is not None and existing_repo.owner_id != owner.id:
        # Cross-user conflict check
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A repository with this identifier is already owned by another account.",
        )

    if existing_repo is None:
        repo_record = RepositoryMetadata(
            repository_id=repo_id,
            owner_id=owner.id,
            name=repo_name,
            storage_path=str(snapshot_path),
            status="analyzed",
        )
        db.add(repo_record)
    else:
        existing_repo.name = repo_name
        existing_repo.storage_path = str(snapshot_path)
        existing_repo.status = "analyzed"
    db.commit()

    analysis_stats = result["analysis"]
    ingestion_stats = result["ingestion"]

    return AnalysisResponse(
        repository_id=repo_id,
        name=repo_name,
        analysis=AnalysisSummary(
            total_entities=analysis_stats.get("total_entities", 0),
            entities_by_kind=analysis_stats.get("entities_by_kind", {}),
            total_relationships=analysis_stats.get("total_relationships", 0),
            relationships_by_type=analysis_stats.get("relationships_by_type", {}),
            unresolved_calls=analysis_stats.get("unresolved_calls", 0),
            external_calls=analysis_stats.get("external_calls", 0),
            validation_errors=analysis_stats.get("validation_errors", 0),
        ),
        ingestion=IngestionSummary(
            nodes_total=ingestion_stats.get("nodes_total", 0),
            nodes_by_label=ingestion_stats.get("nodes_by_label", {}),
            relationships_total=ingestion_stats.get("relationships_total", 0),
            relationships_by_type=ingestion_stats.get("relationships_by_type", {}),
        ),
        message=f"Repository '{repo_name}' analyzed and stored successfully.",
    )


@router.get(
    "/my-repositories",
    response_model=List[RepositoryListItem],
    summary="List all repositories owned by the current user",
)
def list_my_repositories(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> List[RepositoryListItem]:
    """Retrieve all repositories owned by the currently authenticated user."""
    repos = (
        db.query(RepositoryMetadata)
        .filter(RepositoryMetadata.owner_id == current_user.id)
        .order_by(RepositoryMetadata.created_at.desc())
        .all()
    )
    return [RepositoryListItem.model_validate(r) for r in repos]


@router.get(
    "/{repository_id}",
    response_model=RepositoryListItem,
    summary="Get repository metadata with ownership check",
)
def get_repository_details(
    repository_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RepositoryListItem:
    """Retrieve metadata for a specific repository. Ensures caller is the owner."""
    repo = verify_repository_access(repository_id, current_user, db)
    return RepositoryListItem.model_validate(repo)
