"""FastAPI application entry point for Cypher.

Run with:
    uvicorn cypher.main:app --reload

The application connects to Neo4j on startup, initializes the relational database
schema (PostgreSQL/SQLite), and cleanly closes connections on shutdown.
All routes are mounted under /api/v1/.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from cypher.api.routes import api_router
from cypher.config import get_settings
from cypher.db.session import init_db
from cypher.graph.neo4j_client import Neo4jClient, Neo4jConfig

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage database and Neo4j connections for the application lifecycle."""
    settings = get_settings()

    # Fail fast if production misconfigurations exist
    prod_errors = settings.validate_production_readiness()
    if prod_errors:
        err_msg = "Production configuration validation failed: " + "; ".join(prod_errors)
        logger.critical(err_msg)
        raise RuntimeError(err_msg)

    # 1. Initialize Relational Database (PostgreSQL / SQLite)
    try:
        init_db()
        logger.info("Relational database schema initialized.")
    except Exception as exc:
        logger.error("Relational database initialization failed: %s", exc)

    # 2. Connect to Neo4j
    logger.info("Cypher starting up — connecting to Neo4j at %s", settings.neo4j_uri)
    config = Neo4jConfig(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )
    client = Neo4jClient(config=config)

    try:
        client.connect()
        app.state.neo4j_client = client
        logger.info("Neo4j connected successfully.")
    except Exception as exc:
        logger.error("Neo4j connection failed on startup: %s", exc)
        app.state.neo4j_client = None

    yield  # <-- application runs here

    # Shutdown: close the Neo4j driver
    if app.state.neo4j_client is not None:
        app.state.neo4j_client.close()
        logger.info("Neo4j connection closed.")


def create_app() -> FastAPI:
    """Factory function that builds and configures the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Cypher — Code Intelligence Platform",
        description=(
            "Analyzes Python repositories using AST parsing, builds a "
            "Code Knowledge Graph in Neo4j, and exposes structured query APIs."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Allow the React frontend (and local dev tools) to call this API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount all API routes under /api/v1
    app.include_router(api_router, prefix="/api/v1")

    # Serve static UI files and root index.html
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        def read_root():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"message": "Cypher API is online. Static UI not found."}

    return app


# The application instance used by uvicorn.
app = create_app()
