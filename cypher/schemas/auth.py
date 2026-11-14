"""Schemas for user authentication and authorization."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

EMAIL_REGEX = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class UserCreate(BaseModel):
    """Payload for user registration."""

    email: str = Field(
        ...,
        pattern=EMAIL_REGEX,
        description="Unique email address for registration.",
        examples=["developer@example.com"],
    )
    password: str = Field(..., min_length=6, max_length=128, description="Plaintext password.")


class LoginRequest(BaseModel):
    """Payload for logging in with JSON body."""

    email: str = Field(
        ...,
        pattern=EMAIL_REGEX,
        description="Registered email address.",
        examples=["developer@example.com"],
    )
    password: str = Field(..., description="Password.")


class Token(BaseModel):
    """JWT bearer token response."""

    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Payload decoded from JWT token."""

    user_id: int | None = None
    email: str | None = None


class UserResponse(BaseModel):
    """Public user profile response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    is_active: bool
    created_at: datetime
