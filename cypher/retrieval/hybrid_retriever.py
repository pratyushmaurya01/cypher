"""Hybrid retriever — Reciprocal Rank Fusion (RRF) over graph + vector results.

RRF score formula:
    score(item, rank) = 1 / (k + rank)   where k = 60 (standard default)

Each evidence type (graph vs vector) is ranked independently first, then
their scores are summed per dedup key (file_path:start_line:end_line).
The final list is sorted descending by combined RRF score.

RRF preserves the *identity* of each result — a chunk that appears in both
graph and vector retrieval gets a "hybrid" source tag and a higher fused score.
"""

from __future__ import annotations

import logging

from cypher.schemas.rag import FusedEvidence, GraphResult, VectorResult

logger = logging.getLogger(__name__)

# Standard RRF k constant — prevents top-ranked results from dominating too much
_RRF_K = 60


def _rrf_score(rank: int, k: int = _RRF_K) -> float:
    """Return the RRF score for a result at a given 1-based rank position."""
    return 1.0 / (k + rank)


def fuse(
    graph_results: list[GraphResult],
    vector_results: list[VectorResult],
    max_evidence: int = 12,
) -> list[FusedEvidence]:
    """Combine graph and vector results using Reciprocal Rank Fusion.

    Args:
        graph_results:  Ordered list of graph entities (best first).
        vector_results: Ordered list of vector chunks (best first = lowest distance).
        max_evidence:   Maximum number of fused items to return.

    Returns:
        List of FusedEvidence sorted by descending combined RRF score.
    """
    scores: dict[str, float] = {}           # dedup_key → cumulative RRF score
    evidence_map: dict[str, FusedEvidence] = {}   # dedup_key → evidence object
    graph_rank_map: dict[str, int] = {}
    vector_rank_map: dict[str, int] = {}

    # --- Rank graph results (already ordered by GraphRetriever) ---
    for rank, gr in enumerate(graph_results, start=1):
        key = _make_key(gr.file_path, gr.start_line, gr.end_line)
        s = _rrf_score(rank)
        scores[key] = scores.get(key, 0.0) + s
        graph_rank_map[key] = rank
        if key not in evidence_map:
            evidence_map[key] = FusedEvidence(
                dedup_key=key,
                file_path=gr.file_path,
                symbol_name=gr.qualified_name.split(".")[-1] if gr.qualified_name else "",
                qualified_name=gr.qualified_name,
                symbol_type=gr.symbol_type,
                start_line=gr.start_line,
                end_line=gr.end_line,
                rrf_score=0.0,
                source="graph",
                graph_rank=rank,
            )

    # --- Rank vector results (already ordered by VectorRetriever — ascending distance) ---
    for rank, vr in enumerate(vector_results, start=1):
        key = _make_key(vr.file_path, vr.start_line, vr.end_line)
        s = _rrf_score(rank)
        scores[key] = scores.get(key, 0.0) + s
        vector_rank_map[key] = rank
        if key not in evidence_map:
            evidence_map[key] = FusedEvidence(
                dedup_key=key,
                file_path=vr.file_path,
                symbol_name=vr.symbol_name,
                qualified_name=vr.qualified_name,
                symbol_type="Function",        # will be refined by context builder
                start_line=vr.start_line,
                end_line=vr.end_line,
                rrf_score=0.0,
                source="vector",
                vector_rank=rank,
            )
        else:
            # Appeared in both — mark as hybrid
            evidence_map[key].source = "hybrid"
            evidence_map[key].vector_rank = rank

    # --- Write final RRF scores and graph_ranks into evidence objects ---
    for key, ev in evidence_map.items():
        ev.rrf_score = scores[key]
        if key in graph_rank_map:
            ev.graph_rank = graph_rank_map[key]
        if key in vector_rank_map:
            ev.vector_rank = vector_rank_map[key]

    # --- Sort descending by RRF score and cap ---
    fused = sorted(evidence_map.values(), key=lambda e: e.rrf_score, reverse=True)
    result = fused[:max_evidence]

    logger.debug(
        "RRF fusion: graph=%d, vector=%d → fused=%d (top-%d returned)",
        len(graph_results), len(vector_results), len(fused), len(result),
    )
    return result


def _make_key(file_path: str, start_line: int, end_line: int) -> str:
    return f"{file_path}:{start_line}:{end_line}"
