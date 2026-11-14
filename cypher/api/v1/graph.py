"""Graph retrieval endpoints — query the Code Knowledge Graph stored in Neo4j.

All endpoints require a ``repository_id`` query parameter to scope results
to a single repository. Ownership is checked against the database registry:
only the owner of a repository can access its graph data.

GET /api/v1/graph/overview
GET /api/v1/graph/routes
GET /api/v1/graph/function/{qualified_name}/dependencies
GET /api/v1/graph/function/{qualified_name}/callers
GET /api/v1/graph/module/{module_name}/dependencies
GET /api/v1/graph/class/{class_name}/hierarchy
GET /api/v1/graph/dead-code
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from cypher.api.deps import check_graph_access, get_current_user_optional
from cypher.db.models import User
from cypher.db.session import get_db
from cypher.graph import queries
from cypher.schemas.graph import (
    ClassHierarchy,
    DeadCodeCandidate,
    EntityDetail,
    EntityItem,
    FileDependencies,
    FunctionCaller,
    FunctionDependency,
    ModuleDependencies,
    RepositoryOverview,
    RouteItem,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["Graph"])

# Type alias for the common repository_id query parameter
RepoId = Annotated[
    str,
    Query(description="Stable repository ID returned by the analysis endpoint."),
]


def _neo4j(request: Request):
    """Return the shared Neo4j client, or raise 503 if unavailable."""
    client = getattr(request.app.state, "neo4j_client", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Neo4j is not connected.",
        )
    return client


# ---------------------------------------------------------------------------
# Repository overview
# ---------------------------------------------------------------------------

@router.get(
    "/overview",
    response_model=RepositoryOverview,
    summary="High-level statistics for a repository graph",
)
def get_overview(
    request: Request,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> RepositoryOverview:
    """Return counts of modules, classes, functions, calls, and routes for a repository."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        row = queries.get_repository_overview(client, repository_id=repository_id)
    except Exception as exc:
        logger.error("Overview query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return RepositoryOverview(
        repository_id=repository_id,
        total_modules=row.get("total_modules", 0) or 0,
        total_classes=row.get("total_classes", 0) or 0,
        total_functions=row.get("total_functions", 0) or 0,
        total_external_dependencies=row.get("total_externals", 0) or 0,
        total_calls=row.get("total_calls", 0) or 0,
        total_routes=row.get("total_routes", 0) or 0,
    )


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@router.get(
    "/routes",
    response_model=list[RouteItem],
    summary="List all HTTP routes and their handler functions",
)
def get_routes(
    request: Request,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[RouteItem]:
    """Return every ROUTES_TO relationship — URL patterns mapped to handler functions."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        rows = queries.find_all_routes(client, repository_id=repository_id)
    except Exception as exc:
        logger.error("Routes query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return [
        RouteItem(
            source=row.get("source", ""),
            route=row.get("route"),
            http_methods=row.get("http_methods") or [],
            url_name=row.get("url_name"),
            handler=row.get("handler", ""),
            file=row.get("file"),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Function dependency and caller queries
# ---------------------------------------------------------------------------

@router.get(
    "/function/{qualified_name}/dependencies",
    response_model=list[FunctionDependency],
    summary="What does this function call or instantiate?",
)
def get_function_dependencies(
    request: Request,
    qualified_name: str,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[FunctionDependency]:
    """Return all functions and classes called (directly or transitively, up to 3 hops)
    by the given function.
    """
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        rows = queries.find_function_dependencies(
            client, qualified_name=qualified_name, repository_id=repository_id
        )
    except Exception as exc:
        logger.error("Dependencies query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return [
        FunctionDependency(
            target=row.get("target", ""),
            kind=row.get("kind"),
            file=row.get("file"),
            depth=row.get("depth", 1),
        )
        for row in rows
    ]


@router.get(
    "/function/{qualified_name}/callers",
    response_model=list[FunctionCaller],
    summary="Who calls this function?",
)
def get_function_callers(
    request: Request,
    qualified_name: str,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[FunctionCaller]:
    """Return all functions that call the given function (up to 3 hops)."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        rows = queries.find_function_callers(
            client, qualified_name=qualified_name, repository_id=repository_id
        )
    except Exception as exc:
        logger.error("Callers query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return [
        FunctionCaller(
            caller=row.get("caller", ""),
            file=row.get("file"),
            depth=row.get("depth", 1),
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Module dependency query
# ---------------------------------------------------------------------------

@router.get(
    "/module/{module_name}/dependencies",
    response_model=ModuleDependencies,
    summary="What does this module import, and what imports it?",
)
def get_module_dependencies(
    request: Request,
    module_name: str,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> ModuleDependencies:
    """Return both outgoing imports (what this module imports) and incoming imports
    (which modules depend on this one).
    """
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        result = queries.find_module_dependencies(
            client, module_name=module_name, repository_id=repository_id
        )
    except Exception as exc:
        logger.error("Module dependencies query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return ModuleDependencies(
        module_name=module_name,
        imports=result.get("imports", []),
        imported_by=result.get("imported_by", []),
    )


# ---------------------------------------------------------------------------
# Class hierarchy query
# ---------------------------------------------------------------------------

@router.get(
    "/class/{class_name}/hierarchy",
    response_model=ClassHierarchy,
    summary="Superclasses and subclasses of a class",
)
def get_class_hierarchy(
    request: Request,
    class_name: str,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> ClassHierarchy:
    """Return the inheritance chain for a class — both ancestors and descendants."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        rows = queries.find_class_hierarchy(
            client, class_name=class_name, repository_id=repository_id
        )
    except Exception as exc:
        logger.error("Class hierarchy query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    if not rows:
        return ClassHierarchy(class_name=class_name)

    row = rows[0]
    return ClassHierarchy(
        class_name=class_name,
        superclasses=[s for s in (row.get("superclasses") or []) if s],
        subclasses=[s for s in (row.get("subclasses") or []) if s],
    )


# ---------------------------------------------------------------------------
# Dead-code candidates
# ---------------------------------------------------------------------------

@router.get(
    "/dead-code",
    response_model=list[DeadCodeCandidate],
    summary="Functions that appear to never be called",
)
def get_dead_code(
    request: Request,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[DeadCodeCandidate]:
    """Return functions with no incoming CALLS or ROUTES_TO edges."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        rows = queries.find_uncalled_functions(client, repository_id=repository_id)
    except Exception as exc:
        logger.error("Dead code query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return [
        DeadCodeCandidate(
            unused_function=row.get("unused_function", ""),
            file=row.get("file"),
            line=row.get("line"),
        )
        for row in rows
    ]


@router.get(
    "/entities",
    response_model=list[EntityItem],
    summary="List graph entities with filtering and pagination",
)
def list_entities(
    request: Request,
    repository_id: RepoId,
    db: Annotated[Session, Depends(get_db)],
    kind: Annotated[str | None, Query(description="Filter by entity label (e.g. Function, Class, Module)")] = None,
    file_path: Annotated[str | None, Query(description="Filter by relative file path")] = None,
    skip: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
    limit: Annotated[int, Query(ge=1, le=1000, description="Page size limit (max 1000)")] = 100,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[EntityItem]:
    """Return a paginated list of entity nodes in the repository graph."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        rows = queries.find_entities(
            client,
            repository_id=repository_id,
            kind=kind,
            file_path=file_path,
            skip=skip,
            limit=limit,
        )
    except Exception as exc:
        logger.error("List entities query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return [EntityItem.model_validate(r) for r in rows]


@router.get(
    "/entity/{entity_id}",
    response_model=EntityDetail,
    summary="Get entity detail along with incoming and outgoing relationships",
)
def get_entity_detail_endpoint(
    request: Request,
    repository_id: RepoId,
    entity_id: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> EntityDetail:
    """Retrieve full details of an entity node and its connected relationships."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        detail = queries.get_entity_detail(client, repository_id=repository_id, entity_id=entity_id)
    except Exception as exc:
        logger.error("Get entity detail query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    if detail is None:
        raise HTTPException(status_code=404, detail=f"Entity '{entity_id}' not found in repository.")

    return EntityDetail(
        entity=EntityItem.model_validate(detail["entity"]),
        incoming_relationships=detail["incoming_relationships"],
        outgoing_relationships=detail["outgoing_relationships"],
    )


@router.get(
    "/file/dependencies",
    response_model=FileDependencies,
    summary="Explore file-level import relationships",
)
def get_file_dependencies_endpoint(
    request: Request,
    repository_id: RepoId,
    file_path: Annotated[str, Query(description="Relative file path within repository")],
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> FileDependencies:
    """Explore file-to-file import relationships."""
    check_graph_access(repository_id, db, current_user)
    client = _neo4j(request)
    try:
        deps = queries.find_file_dependencies(client, repository_id=repository_id, file_path=file_path)
    except Exception as exc:
        logger.error("File dependencies query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Graph query failed.")

    return FileDependencies.model_validate(deps)
