"""LangGraph StateGraph builder for Cypher Hybrid RAG.

Architecture:
                       [START]
                          │
                          ▼
                  [understand_query] (LLM Call 1)
                          │
                          ▼
                   [retrieve_graph]
                          │
                          ▼
                  [retrieve_vector]
                          │
                          ▼
                    [rrf_fusion]
                          │
                          ▼
                   [build_context]
                          │
                          ▼
                  [generate_answer] (LLM Call 2)
                          │
                          ▼
                        [END]

Every query receives a grounded, well-explained answer from Gemini with exact code blocks.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from cypher.rag_graph.nodes import (
    node_build_context,
    node_generate_answer,
    node_retrieve_graph,
    node_retrieve_vector,
    node_rrf_fusion,
    node_understand_query,
)
from cypher.rag_graph.state import RAGState


def build_rag_graph():
    """Build and compile the LangGraph workflow."""
    workflow = StateGraph(RAGState)

    # 1. Register Nodes
    workflow.add_node("understand_query", node_understand_query)
    workflow.add_node("retrieve_graph", node_retrieve_graph)
    workflow.add_node("retrieve_vector", node_retrieve_vector)
    workflow.add_node("rrf_fusion", node_rrf_fusion)
    workflow.add_node("build_context", node_build_context)
    workflow.add_node("generate_answer", node_generate_answer)

    # 2. Linear execution flow (exactly 2 LLM calls per query)
    workflow.add_edge(START, "understand_query")
    workflow.add_edge("understand_query", "retrieve_graph")
    workflow.add_edge("retrieve_graph", "retrieve_vector")
    workflow.add_edge("retrieve_vector", "rrf_fusion")
    workflow.add_edge("rrf_fusion", "build_context")
    workflow.add_edge("build_context", "generate_answer")
    workflow.add_edge("generate_answer", END)

    return workflow.compile()


# Singleton compiled graph
rag_pipeline_graph = build_rag_graph()
