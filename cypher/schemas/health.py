"""Response schema for the health-check endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Returned by GET /health."""

    status: str           # "ok" or "degraded"
    neo4j: str            # "connected" or "unreachable"
    version: str          # application version string
