# Stage 5 Plan: End-to-End Hybrid RAG Pipeline for Cypher

## 1. Objective & Architectural Alignment
Build an end-to-end question-answering engine combining:
1. **Deterministic Static Analysis & Graph Retrieval (Neo4j)**: AST symbols, calls, inheritance, imports, routes.
2. **Dense Semantic Retrieval (ChromaDB + SentenceTransformers / Gemini Embeddings)**: AST-aware symbol chunks.
3. **Reciprocal Rank Fusion (RRF) & Multi-Hop Query Routing**: Dynamic impact analysis for questions like *"If I change User in models.py, what breaks across the project?"*
4. **LLM Provider Abstraction (Google Gemini API free tier + Mock / Fallback)**: Grounded answers with exact file paths and line ranges.
5. **Authenticated REST API**: `POST /api/v1/chat/{repository_id}`.
6. **Empirical Evaluation Benchmark**: 25+ automated evaluation questions on the sample Django repository.

---

## 2. Component Architecture & Directory Structure

```
cypher/
├── embeddings/
│   ├── base.py                 # Abstract Base Class: BaseEmbeddingProvider
│   ├── local_embedding.py      # SentenceTransformers (all-MiniLM-L6-v2) for local/offline
│   └── gemini_embedding.py     # Gemini text-embedding-004 provider
├── vectorstore/
│   ├── base.py                 # Abstract Base Class: BaseVectorStore
│   ├── chunker.py              # AST-aware code chunker (Functions, Classes, Modules)
│   └── chroma_store.py         # Persistent ChromaDB client with tenant/repo isolation
├── retrieval/
│   ├── graph_retriever.py      # Multi-hop Neo4j query orchestrator (Callers, Callees, Inheritors, Impact)
│   ├── vector_retriever.py     # Semantic top-k retriever
│   ├── hybrid_retriever.py     # Reciprocal Rank Fusion (RRF), deduplication & ranking
│   └── context_builder.py      # Bounded context assembly with citation anchors
├── llm/
│   ├── base.py                 # Abstract Base Class: BaseLLMProvider
│   ├── gemini_llm.py           # Google Gemini 1.5 Flash / 2.5 Flash implementation
│   └── mock_llm.py             # Deterministic mock provider for unit tests & offline mode
├── services/
│   └── rag_service.py          # Unified high-level RAG orchestration service
├── schemas/
│   └── rag.py                  # Pydantic v2 schemas: ChatRequest, ChatResponse, SourceCitation, RetrievalDiagnostics
└── api/v1/
    └── chat.py                 # Authenticated POST /api/v1/chat/{repository_id} endpoint
```

---

## 3. Step-by-Step Implementation Sequence

- **Step 1: Security Cleanup & Grounding** (COMPLETED)
  - Untracked `.env`, `cypher.db`, `test.py`, and `storage/` from Git.
  - Updated `.gitignore`.
  - Regression verified: 132/132 tests passing.

- **Step 2: Vector Embeddings & Code-Aware Chunker**
  - Implement `cypher/vectorstore/chunker.py` leveraging existing `SourceCodeService` and AST metadata.
  - Implement `cypher/embeddings/base.py` and `local_embedding.py` + `gemini_embedding.py`.
  - Implement `cypher/vectorstore/chroma_store.py` with idempotent upsert and repository isolation.

- **Step 3: Graph Retriever & Impact Analysis Engine**
  - Implement `cypher/retrieval/graph_retriever.py`:
    - Direct symbol definition & metadata lookup.
    - Multi-hop impact traversal: Class/Model -> Inheritors & Importers -> Calling Views/Functions -> API Routes.
    - Reverse call hierarchy search (who calls X?).

- **Step 4: Hybrid Fusion & Context Construction**
  - Implement `cypher/retrieval/hybrid_retriever.py` with Reciprocal Rank Fusion (RRF).
  - Implement `cypher/retrieval/context_builder.py` formatting code blocks with `[file_path:start_line-end_line]`.

- **Step 5: LLM Provider Abstraction & RAG Service**
  - Implement `cypher/llm/base.py`, `gemini_llm.py` (free-tier `gemini-1.5-flash`), and `mock_llm.py`.
  - Implement `cypher/services/rag_service.py` coordinating indexing, retrieval, context construction, and LLM generation.

- **Step 6: Chat API Endpoint & Dependency Injection**
  - Implement `cypher/schemas/rag.py` and `cypher/api/v1/chat.py`.
  - Mount router in `cypher/api/routes.py`.

- **Step 7: Automated Test Suite & Benchmark Evaluation**
  - Unit tests covering chunking, embeddings, vector indexing, graph retrieval, hybrid fusion, LLM prompts, and API endpoints.
  - Create `eval/evaluation_benchmark.py` running 25+ real-world questions against `sample_repo` (Django).
  - Compute Recall@K, Precision@K, MRR, citation validity, and latency.

- **Step 8: Final Documentation & Completion Report**
  - Document RAG pipeline, API contracts, benchmark results, and Gemini setup instructions.
