"""Central API router — collects all v1 sub-routers in one place.

``main.py`` imports only ``api_router`` from here.  Adding a new feature
means creating a new router file in ``api/v1/`` and including it below.
"""

from __future__ import annotations

from fastapi import APIRouter

from cypher.api.v1 import auth, graph, health, repository, source

api_router = APIRouter()

# Health check
api_router.include_router(health.router)

# User authentication
api_router.include_router(auth.router)

# Repository upload, registry, and analysis
api_router.include_router(repository.router)

# Graph retrieval queries
api_router.include_router(graph.router)

# Source code snapshot and line range retrieval
api_router.include_router(source.router)
