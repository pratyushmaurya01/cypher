"""Health-check endpoint.

GET /api/v1/health

Returns the application status and Neo4j connectivity.
This endpoint never raises HTTP 500 — it always returns 200 with a
``status`` field that is either ``"ok"`` or ``"degraded"``.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from cypher.schemas.health import HealthResponse

router = APIRouter(tags=["Health"])

_VERSION = "0.1.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Application and database health check",
)
def health_check(request: Request) -> HealthResponse:
    """Return server liveness and Neo4j connectivity status.

    - ``status``: ``"ok"`` if everything is reachable, ``"degraded"`` otherwise.
    - ``neo4j``: ``"connected"`` or ``"unreachable"``.
    - ``version``: the application version string.

    The endpoint always returns HTTP 200 so that load-balancers and monitoring
    tools can distinguish between *the server is dead* (no response at all) and
    *the server is alive but Neo4j is down* (200 + degraded status).
    """
    # The Neo4j client is attached to the app state in main.py lifespan.
    neo4j_client = getattr(request.app.state, "neo4j_client", None)

    if neo4j_client is not None:
        try:
            reachable = neo4j_client.verify_connectivity()
        except Exception:
            reachable = False
    else:
        reachable = False

    neo4j_status = "connected" if reachable else "unreachable"
    overall_status = "ok" if reachable else "degraded"

    return HealthResponse(
        status=overall_status,
        neo4j=neo4j_status,
        version=_VERSION,
    )
