"""LangGraph State definition for the Cypher Hybrid RAG pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from cypher.schemas.rag import (
    FusedEvidence,
    GraphResult,
    QueryUnderstanding,
    RetrievalDiagnostics,
    SourceCitation,
    VectorResult,
)


class RAGState(TypedDict, total=False):
    """Shared state dictionary passed across all nodes in the LangGraph."""

    # Input parameters
    question: str
    repository_id: str
    owner_id: int | str
    snapshot_dir: Path
    neo4j_client: Any
    start_time: float

    # Query Understanding (Output of 1st LLM call)
    understanding: QueryUnderstanding | None
    is_deterministic: bool

    # Retrieval evidence (Intermediate)
    graph_results: list[GraphResult]
    vector_results: list[VectorResult]
    fused_evidence: list[FusedEvidence]

    # Context & Grounded Citations
    context_string: str
    citations: list[SourceCitation]

    # Generation (Output of 2nd LLM call)
    final_answer: str

    # Diagnostics & Timings
    diagnostics: RetrievalDiagnostics
