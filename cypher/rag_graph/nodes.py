"""Individual nodes for the LangGraph RAG StateGraph.

Guarantees:
- Exactly 2 LLM calls on full hybrid path (understanding + answer generation).
- Exactly 1 LLM call on deterministic path (understanding only, Neo4j handles rest).
- Neo4j, ChromaDB, RRF and SourceCodeService remain under strict local control.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from cypher.config import get_settings
from cypher.llm.gemini_llm import GeminiClient
from cypher.rag_graph.state import RAGState
from cypher.retrieval import context_builder, hybrid_retriever
from cypher.retrieval.graph_retriever import GraphRetriever
from cypher.retrieval.vector_retriever import VectorRetriever
from cypher.vectorstore.chroma_store import ChromaStore

logger = logging.getLogger(__name__)


def node_understand_query(state: RAGState) -> dict[str, Any]:
    """Node 1: Parse user question using Gemini into structured QueryUnderstanding (LLM Call 1)."""
    question = state["question"]
    gemini = GeminiClient()
    understanding = gemini.understand_query(question)

    return {
        "understanding": understanding,
        "is_deterministic": bool(understanding.is_deterministic),
    }


def node_deterministic_query(state: RAGState) -> dict[str, Any]:
    """Node 2 (Fast Path): Execute direct parameterized queries against Neo4j without vector/LLM."""
    from cypher.graph.queries import find_entities

    understanding = state["understanding"]
    neo4j_client = state["neo4j_client"]
    repo_id = state["repository_id"]
    diagnostics = state.get("diagnostics")

    entity_types = (understanding.graph_search.entity_types if understanding else None) or ["Class", "Function"]
    intent = understanding.intent if understanding else "overview"

    t0 = time.monotonic()
    all_results = []
    for etype in entity_types:
        rows = find_entities(neo4j_client, repo_id, kind=etype, limit=50)
        all_results.extend(rows)

    if diagnostics:
        diagnostics.graph_latency_ms = (time.monotonic() - t0) * 1000
        diagnostics.graph_entities_found = len(all_results)

    if not all_results:
        answer = f"No {', '.join(entity_types)} entities found in this repository."
    else:
        lines = [f"## {intent.replace('_', ' ').title()}\n"]
        for row in all_results:
            kind = row.get("kind", "?")
            qname = row.get("qualified_name", "?")
            fp = row.get("file_path", "?")
            ln = row.get("line", "?")
            lines.append(f"- **{kind}** `{qname}` — `{fp}` (line {ln})")
        answer = "\n".join(lines)

    return {
        "final_answer": answer,
        "citations": [],
    }


def node_retrieve_graph(state: RAGState) -> dict[str, Any]:
    """Node 3A: Parameterized Knowledge Graph retrieval from Neo4j."""
    understanding = state["understanding"]
    neo4j_client = state["neo4j_client"]
    repo_id = state["repository_id"]
    diagnostics = state.get("diagnostics")
    settings = get_settings()

    t0 = time.monotonic()
    graph_results = []
    if understanding and understanding.retrieval.graph and neo4j_client:
        try:
            gr = GraphRetriever(neo4j_client)
            graph_results = gr.retrieve(
                understanding, repo_id, top_k=settings.rag_graph_top_k
            )
        except Exception as exc:
            logger.warning("node_retrieve_graph error: %s", exc)

    if diagnostics:
        diagnostics.graph_latency_ms = (time.monotonic() - t0) * 1000
        diagnostics.graph_entities_found = len(graph_results)

    return {"graph_results": graph_results}


def node_retrieve_vector(state: RAGState) -> dict[str, Any]:
    """Node 3B: Semantic similarity search from ChromaDB."""
    understanding = state["understanding"]
    repo_id = state["repository_id"]
    diagnostics = state.get("diagnostics")
    settings = get_settings()

    t0 = time.monotonic()
    vector_results = []
    if understanding and understanding.retrieval.vector:
        try:
            from cypher.embeddings.gemini_embedding import GeminiEmbeddingProvider

            embedder = GeminiEmbeddingProvider()
            store = ChromaStore()
            vr = VectorRetriever(store, embedder)
            vector_results = vr.retrieve(
                understanding, repo_id, top_k=settings.rag_vector_top_k
            )
        except Exception as exc:
            logger.warning("node_retrieve_vector error: %s", exc)

    if diagnostics:
        diagnostics.vector_latency_ms = (time.monotonic() - t0) * 1000
        diagnostics.vector_chunks_found = len(vector_results)

    return {"vector_results": vector_results}


def node_rrf_fusion(state: RAGState) -> dict[str, Any]:
    """Node 4: Reciprocal Rank Fusion across graph and vector evidence."""
    graph_results = state.get("graph_results", [])
    vector_results = state.get("vector_results", [])
    diagnostics = state.get("diagnostics")
    settings = get_settings()

    fused = hybrid_retriever.fuse(
        graph_results=graph_results,
        vector_results=vector_results,
        max_evidence=settings.rag_max_evidence,
    )

    if diagnostics:
        diagnostics.fused_evidence_count = len(fused)

    return {"fused_evidence": fused}


def node_build_context(state: RAGState) -> dict[str, Any]:
    """Node 5: SourceCodeService extraction of exact lines from disk snapshot."""
    fused = state.get("fused_evidence", [])
    snapshot_dir = state["snapshot_dir"]
    repo_id = state["repository_id"]
    settings = get_settings()

    context_str, citations = context_builder.build_context(
        evidence_list=fused,
        snapshot_dir=snapshot_dir,
        repository_id=repo_id,
        max_chars=settings.rag_context_max_tokens * 4,
    )

    return {
        "context_string": context_str,
        "citations": citations,
    }


def node_generate_answer(state: RAGState) -> dict[str, Any]:
    """Node 6: Generate final answer with inline code citations via Gemini (LLM Call 2)."""
    question = state["question"]
    understanding = state["understanding"]
    context_str = state.get("context_string", "")
    citations = state.get("citations", [])

    gemini = GeminiClient()
    if understanding and getattr(understanding, "intent", "") == "greeting":
        answer = gemini.generate_answer(question, understanding, "")
    elif not citations:
        answer = (
            "No relevant code could be retrieved from the repository snapshot. "
            "Ensure the repository has been analyzed and files exist on disk."
        )
    else:
        answer = gemini.generate_answer(question, understanding, context_str)

    return {"final_answer": answer}
