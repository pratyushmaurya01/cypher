"""User authentication endpoints: signup, login, and user profile."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cypher.api.deps import get_current_user
from cypher.core.security import create_access_token, hash_password, verify_password
from cypher.db.models import User
from cypher.db.session import get_db
from cypher.schemas.auth import LoginRequest, Token, UserCreate, UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def signup(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
) -> UserResponse:
    """Register a new user account with unique email and secure hashed password."""
    normalized_email = payload.email.strip().lower()

    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists.",
        )

    hashed = hash_password(payload.password)
    new_user = User(
        email=normalized_email,
        hashed_password=hashed,
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    logger.info("New user registered: %s (id=%d)", new_user.email, new_user.id)
    return UserResponse.model_validate(new_user)


@router.post(
    "/login",
    response_model=Token,
    summary="Log in and retrieve JWT access token",
)
def login(
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> Token:
    """Authenticate with email and password and return a signed JWT access token."""
    normalized_email = payload.email.strip().lower()

    user = db.query(User).filter(User.email == normalized_email).first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    access_token = create_access_token(
        subject=user.id,
        extra_claims={"email": user.email},
    )
    logger.info("User logged in successfully: %s (id=%d)", user.email, user.id)
    return Token(access_token=access_token, token_type="bearer")


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get currently authenticated user profile",
)
def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return profile details for the currently authenticated user."""
    return UserResponse.model_validate(current_user)
