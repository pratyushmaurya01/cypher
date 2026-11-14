"""FastAPI request dependencies: database session, authentication, and authorization."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from cypher.core.security import decode_access_token
from cypher.db.models import RepositoryMetadata, User
from cypher.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False,
)


def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Validate JWT token and return the authenticated User.

    Raises:
        HTTPException: 401 if missing, invalid, or expired token, or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception

    try:
        payload = decode_access_token(token)
        user_id_str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (jwt.PyJWTError, ValueError):
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if user is None:
        raise credentials_exception
    return user


def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    """Return the authenticated User if token is provided, or None."""
    if not token:
        return None
    try:
        return get_current_user(token, db)
    except HTTPException:
        return None


def verify_repository_access(
    repository_id: str,
    current_user: User,
    db: Session,
) -> RepositoryMetadata:
    """Verify that a repository exists and is owned by the current user.

    Raises:
        HTTPException: 404 if repository does not exist in registry.
        HTTPException: 403 if repository belongs to another user.
    """
    repo = (
        db.query(RepositoryMetadata)
        .filter(RepositoryMetadata.repository_id == repository_id)
        .first()
    )
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository '{repository_id}' not found in registry.",
        )

    if repo.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this repository.",
        )

    return repo


def check_graph_access(
    repository_id: str,
    db: Session,
    current_user: User | None = None,
) -> RepositoryMetadata | None:
    """Enforce cross-user data isolation for graph queries.

    - If the repository is registered under a registered user:
        - An unauthenticated request is rejected with 401 Unauthorized.
        - A request from another user is rejected with 403 Forbidden.
        - A request from the owner is permitted.
    - If the repository is owned by dev-anonymous or not yet in registry:
        - Permitted for backwards compatibility in local dev/mock test suites.
    """
    repo = (
        db.query(RepositoryMetadata)
        .filter(RepositoryMetadata.repository_id == repository_id)
        .first()
    )
    if repo is not None:
        if current_user is None:
            owner = db.query(User).filter(User.id == repo.owner_id).first()
            if owner and owner.email == "dev-anonymous@cypher.local":
                return repo
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required to access this repository.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if repo.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to this repository.",
            )
    return repo
