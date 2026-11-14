"""Analysis service — orchestrates ZIP extraction, AST analysis, and Neo4j ingestion.

This is the only place that calls ``analyze_repository()`` and ``GraphBuilder``.
API routes must never call these directly.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from cypher.analyzer.engine import analyze_repository
from cypher.graph.graph_builder import GraphBuilder
from cypher.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AnalysisServiceError(Exception):
    """Base error raised by the service layer."""


class InvalidZipError(AnalysisServiceError):
    """Raised when the uploaded file is not a valid ZIP archive."""


class EmptyRepositoryError(AnalysisServiceError):
    """Raised when no Python files are found after unpacking."""


class PathTraversalError(AnalysisServiceError):
    """Raised when a ZIP entry tries to escape the extraction directory."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_extract(zip_path: Path, extract_dir: Path) -> None:
    """Extract a ZIP file, rejecting any entries with path traversal attempts.

    A ZIP file could contain entries like ``../../etc/passwd``.  We check
    every entry before extracting to prevent writing outside ``extract_dir``.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            # Resolve the full target path and confirm it stays inside extract_dir
            target = (extract_dir / member).resolve()
            if not str(target).startswith(str(extract_dir.resolve())):
                raise PathTraversalError(
                    f"ZIP entry '{member}' would escape the extraction directory."
                )
        zf.extractall(extract_dir)


def _find_python_root(extract_dir: Path) -> Path:
    """Find the actual Python project root inside the extraction directory.

    When a ZIP contains a single top-level folder (common on GitHub downloads,
    e.g. ``myproject-main/``), descend into it automatically so that module
    names are computed relative to the project root, not the zip wrapper.
    """
    entries = list(extract_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        # Descend one level if the ZIP has a single top-level folder
        return entries[0]
    return extract_dir


def _repo_id_from_path(root: Path) -> str:
    """Generate a stable repository ID from the absolute root path."""
    return "repo_" + hashlib.sha256(str(root).encode()).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Service functions
# ---------------------------------------------------------------------------

def extract_zip(
    zip_bytes: bytes,
    *,
    max_bytes: int,
    work_dir: Path,
) -> tuple[Path, str, int]:
    """Save, validate and extract a ZIP upload.

    Returns:
        (python_root, repo_name, python_file_count)

    Raises:
        InvalidZipError: file is not a ZIP or is corrupt.
        PathTraversalError: a ZIP entry attempts path traversal.
        AnalysisServiceError: file exceeds the size limit.
    """
    if len(zip_bytes) > max_bytes:
        raise AnalysisServiceError(
            f"Upload exceeds the maximum allowed size of {max_bytes // (1024 * 1024)} MB."
        )

    zip_path = work_dir / "upload.zip"
    zip_path.write_bytes(zip_bytes)

    if not zipfile.is_zipfile(zip_path):
        raise InvalidZipError("The uploaded file is not a valid ZIP archive.")

    extract_dir = work_dir / "extracted"
    extract_dir.mkdir()

    _safe_extract(zip_path, extract_dir)

    python_root = _find_python_root(extract_dir)
    repo_name = python_root.name

    py_files = list(python_root.rglob("*.py"))
    py_count = len(py_files)

    return python_root, repo_name, py_count


def run_analysis(
    repo_root: Path,
    neo4j_client: Neo4jClient,
    *,
    clear_existing: bool = True,
) -> dict[str, Any]:
    """Run the full analysis pipeline and ingest results into Neo4j.

    Steps:
      1. analyze_repository() — AST parse + symbol resolution + graph build
      2. GraphBuilder.ingest() — write nodes and relationships to Neo4j

    Returns a dict with ``analysis`` and ``ingestion`` summary dicts.
    """
    logger.info("Starting analysis of repository at: %s", repo_root)

    # Step 1 — Run the analysis engine (pure Python, no DB calls)
    graph_data = analyze_repository(repo_root)

    analysis_stats = graph_data.get("stats", {})
    logger.info(
        "Analysis complete: %d entities, %d relationships",
        analysis_stats.get("total_entities", 0),
        analysis_stats.get("total_relationships", 0),
    )

    # Step 2 — Write to Neo4j
    builder = GraphBuilder(client=neo4j_client)
    ingestion_summary = builder.ingest(
        graph_data,
        clear_existing_repo=clear_existing,
    )

    logger.info("Ingestion complete: %s", ingestion_summary)

    return {
        "repository_id": ingestion_summary["repository_id"],
        "analysis": analysis_stats,
        "ingestion": ingestion_summary,
    }
