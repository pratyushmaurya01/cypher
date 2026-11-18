"""Chat API — POST /api/v1/chat/{repository_id}

Endpoint for the hybrid RAG question-answering pipeline.
Requires authentication and repository ownership.
Returns 503 if GEMINI_API_KEY is not configured.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from cypher.api.deps import get_current_user, verify_repository_access
from cypher.config import get_settings
from cypher.db.models import User
from cypher.db.session import get_db
from cypher.llm.gemini_llm import GeminiLLMError
from cypher.schemas.rag import ChatRequest, ChatResponse
from cypher.services.rag_service import RAGService, RAGServiceError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "/{repository_id}",
    response_model=ChatResponse,
    summary="Ask a natural-language question about an analyzed repository",
)
def chat(
    repository_id: str,
    body: ChatRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ChatResponse:
    """Run the hybrid RAG pipeline to answer a question about a repository.

    - Requires authentication (Bearer JWT).
    - Caller must own the repository (403 otherwise).
    - Repository must have status 'analyzed' (404 / 422 otherwise).
    - Returns 503 if GEMINI_API_KEY is not set.
    - Returns 503 if Gemini API quota is exhausted or the key is invalid.

    The response contains:
    - ``answer``: Rich Markdown narrative with inline code blocks.
    - ``sources``: Validated citations with file paths and line numbers.
    - ``retrieval_diagnostics``: Latency and count stats for the pipeline.
    """
    settings = get_settings()

    # 1. Check RAG is enabled
    if not settings.rag_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chat (RAG) is not enabled on this server. "
                "Set GEMINI_API_KEY in the server's .env file to activate it."
            ),
        )

    # 2. Verify repository ownership
    repo = verify_repository_access(repository_id, current_user, db)

    # 3. Verify repository is analyzed
    if repo.status != "analyzed":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Repository '{repository_id}' has status '{repo.status}'. "
                "It must be fully analyzed before you can ask questions about it."
            ),
        )

    # 4. Resolve snapshot directory
    snapshot_dir = Path(repo.storage_path)
    if not snapshot_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Repository snapshot not found on disk at '{repo.storage_path}'. "
                "Re-upload and analyze the repository."
            ),
        )

    # 5. Get Neo4j client from app state
    neo4j_client = getattr(request.app.state, "neo4j_client", None)
    if neo4j_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph database (Neo4j) is not connected. Check server configuration.",
        )

    # 6. Run RAG pipeline
    try:
        svc = RAGService()
        response = svc.answer(
            question=body.question,
            repository_id=repository_id,
            owner_id=current_user.id,
            neo4j_client=neo4j_client,
            snapshot_dir=snapshot_dir,
        )
        return response

    except RAGServiceError as exc:
        logger.error("RAGServiceError for repo=%s: %s", repository_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    except GeminiLLMError as exc:
        msg = str(exc)
        logger.error("GeminiLLMError for repo=%s: %s", repository_id, msg)
        # Quota / auth errors → 503; others → 502
        if "quota" in msg.lower() or "api key" in msg.lower() or "rate" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=msg,
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini API error: {msg}",
        )
    except Exception as exc:
        logger.error(
            "Unexpected error in chat endpoint for repo=%s: %s", repository_id, exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "An unexpected error occurred. Check server logs."
                if not settings.is_development
                else str(exc)
            ),
        )
