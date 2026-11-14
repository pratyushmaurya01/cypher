"""Response schemas for repository upload and analysis endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class UploadResponse(BaseModel):
    """Returned when a ZIP file is successfully uploaded and unpacked."""

    repository_id: str = Field(..., description="Stable ID derived from the repository path.")
    name: str = Field(..., description="Human-readable repository name.")
    files_found: int = Field(..., description="Number of Python files discovered.")
    message: str


class AnalysisSummary(BaseModel):
    """Counts of entities and relationships produced by analysis."""

    total_entities: int
    entities_by_kind: dict[str, int]
    total_relationships: int
    relationships_by_type: dict[str, int]
    unresolved_calls: int
    external_calls: int
    validation_errors: int


class IngestionSummary(BaseModel):
    """Counts of nodes and relationships written to Neo4j."""

    nodes_total: int
    nodes_by_label: dict[str, int]
    relationships_total: int
    relationships_by_type: dict[str, int]


class AnalysisResponse(BaseModel):
    """Returned when analysis and Neo4j ingestion complete successfully."""

    repository_id: str
    name: str
    analysis: AnalysisSummary
    ingestion: IngestionSummary
    message: str


class RepositoryListItem(BaseModel):
    """Metadata item for an owned repository."""

    model_config = ConfigDict(from_attributes=True)

    repository_id: str
    name: str
    status: str
    storage_path: Optional[str] = None
    created_at: datetime
