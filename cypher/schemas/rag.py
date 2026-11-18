"""Pydantic v2 schemas for the RAG (Retrieval-Augmented Generation) pipeline.

These models are shared across:
  - cypher/llm/gemini_llm.py   (QueryUnderstanding is validated here)
  - cypher/api/v1/chat.py      (ChatRequest / ChatResponse are API contracts)
  - cypher/retrieval/*         (GraphResult / VectorResult are internal types)
  - cypher/services/rag_service.py

No circular imports — this module imports only from Pydantic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Query Understanding (output of Gemini Call 1)
# ---------------------------------------------------------------------------

class GraphSearchConfig(BaseModel):
    """Describes how to traverse the Neo4j knowledge graph."""

    entity_types: list[str] = Field(
        default_factory=lambda: ["Function", "Class"],
        description="Node labels to search for.",
    )
    relationship_types: list[str] = Field(
        default_factory=lambda: ["CALLS", "IMPORTS"],
        description="Edge types to traverse.",
    )
    direction: str = Field(
        default="both",
        description="Traversal direction: incoming | outgoing | both.",
    )
    max_depth: int = Field(
        default=2,
        description="Maximum traversal depth (capped at 3 by security sanitizer).",
    )


class RetrievalConfig(BaseModel):
    """Flags controlling which retrievers are activated."""

    vector: bool = True
    graph: bool = True


class QueryUnderstanding(BaseModel):
    """Structured representation of a user's natural-language question.

    Produced by Gemini (Call 1) and validated + sanitized before use.
    """

    intent: str = Field(
        ...,
        description=(
            "One of: locate_symbol | trace_calls | explain_model | find_route | "
            "impact_analysis | architecture_overview | debug_error | generic_search"
        ),
    )
    language: str = Field(
        default="english",
        description="Detected question language: english | hindi | hinglish.",
    )
    entities: list[str] = Field(
        default_factory=list,
        description="Symbol/class/function names mentioned in the question.",
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Technical keywords for semantic (vector) search.",
    )
    search_queries: list[str] = Field(
        ...,
        description="Rephrased questions optimised for embedding-based retrieval.",
    )
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    graph_search: GraphSearchConfig = Field(default_factory=GraphSearchConfig)
    is_deterministic: bool = Field(
        default=False,
        description="True when the question can be answered by a direct graph query (e.g. 'list all models').",
    )


# ---------------------------------------------------------------------------
# Retrieval Result Types (internal — not exposed in the API)
# ---------------------------------------------------------------------------

class GraphResult(BaseModel):
    """A single entity returned from Neo4j graph traversal."""

    entity_id: str = ""
    qualified_name: str
    file_path: str
    start_line: int = 0
    end_line: int = 0
    symbol_type: str = "Function"
    relationship_type: str = ""
    score: float = 1.0          # Graph results always start at 1.0 before RRF


class VectorResult(BaseModel):
    """A single code chunk returned from ChromaDB semantic search."""

    chunk_id: str
    file_path: str
    symbol_name: str
    qualified_name: str
    start_line: int
    end_line: int
    score: float                # Raw cosine similarity distance (lower = more similar in Chroma)
    snippet: str = ""           # Pre-stored embed_text for context


# ---------------------------------------------------------------------------
# Evidence (after RRF fusion + source-code validation)
# ---------------------------------------------------------------------------

class FusedEvidence(BaseModel):
    """A ranked evidence item after Reciprocal Rank Fusion."""

    dedup_key: str              # file_path:start_line:end_line
    file_path: str
    symbol_name: str
    qualified_name: str
    symbol_type: str
    start_line: int
    end_line: int
    rrf_score: float
    source: str                 # "graph" | "vector" | "hybrid"
    graph_rank: int | None = None
    vector_rank: int | None = None


# ---------------------------------------------------------------------------
# API Schemas (public contract)
# ---------------------------------------------------------------------------

class SourceCitation(BaseModel):
    """A validated code citation included in the final ChatResponse."""

    file_path: str
    symbol_name: str
    symbol_type: str
    start_line: int
    end_line: int
    snippet: str = Field(
        default="",
        description="Exact source code fetched from the snapshot.",
    )
    score: float = 0.0
    source: str = Field(
        default="",
        description="Origin of the evidence: graph | vector | hybrid.",
    )


class RetrievalDiagnostics(BaseModel):
    """Timing and count diagnostics for the RAG pipeline — useful for debugging."""

    graph_entities_found: int = 0
    vector_chunks_found: int = 0
    fused_evidence_count: int = 0
    graph_latency_ms: float = 0.0
    vector_latency_ms: float = 0.0
    total_latency_ms: float = 0.0


class ChatRequest(BaseModel):
    """Payload for the POST /chat/{repository_id} endpoint."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural-language question about the repository (English / Hindi / Hinglish).",
    )


class ChatResponse(BaseModel):
    """Full response from the RAG pipeline."""

    repository_id: str
    question: str
    intent: str
    answer: str = Field(
        description="Rich Markdown answer with inline code blocks embedded in the narrative.",
    )
    sources: list[SourceCitation] = Field(
        default_factory=list,
        description="Validated source citations used to generate the answer.",
    )
    retrieval_diagnostics: RetrievalDiagnostics = Field(
        default_factory=RetrievalDiagnostics,
    )
