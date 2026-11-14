# Pre-Stage 5 Master Implementation Plan: Cypher Code Intelligence Platform

## Architecture & Subagent Review Incorporated
- **Upload Streaming:** Stream in chunks (`await file.read(chunk_size)`) to abort immediately on byte overflow before full memory spooling.
- **ZIP Bomb Defense:** 4-tier pre-extraction inspection (total uncompressed size, compression ratio > 100, file count > 10,000, reject nested archives).
- **Windows-Safe Atomic Snapshot Staging:** Unique staging per job (`.staging_{uuid}`), rename promotion with rollback cleanup on exception.
- **Rollback Sequencing:** Failure order (Neo4j rollback → disk staging unlinked → PostgreSQL rollback); Deletion order (PostgreSQL ownership check → Neo4j graph detached → PostgreSQL cascade → disk snapshots wiped).
- **Alembic SQLite Batch Mode:** Set `render_as_batch=True` to support SQLite dev/test databases seamlessly alongside PostgreSQL.
- **Pagination Caps:** Default `limit=100`, max `limit=1000` on graph retrieval endpoints.

---

## Phase 1: Upload Security & Atomic Snapshot Staging (Stage 4.1 Finish)
- **Task 1.1:** Chunked stream upload size enforcement & ZIP bomb protection in `analysis_service.py` and `repository.py`.
- **Task 1.2:** Atomic snapshot staging (`.staging_{uuid}`) and promotion to `v{version}` with rollback cleanup in `source_code_service.py`.
- **Task 1.3:** Unit and API tests for Phase 1 (`tests/test_upload_staging.py`). Verify 100% pass across all tests.

## Phase 2: Database Migrations & Repository Lifecycle Management (Stage 4.2 & 4.7)
- **Task 2.1:** Install & configure Alembic (`alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial_schema.py`) with `render_as_batch=True`.
- **Task 2.2:** Implement repository deletion service & endpoint `DELETE /api/v1/repository/{repository_id}` (PostgreSQL cascade, Neo4j graph removal, disk snapshot deletion).
- **Task 2.3:** Add database transaction rollback and error handling on ingestion failures.
- **Task 2.4:** Write tests for Alembic migration, repository deletion, and partial failure cleanup (`tests/test_lifecycle_alembic.py`).

## Phase 3: Extended Graph Exploration APIs & Diagnostics (Stage 4.3 - 4.5)
- **Task 3.1:** Implement entity listing `GET /api/v1/graph/entities` with filtering (`kind`, `file_path`) and pagination (`limit`, `skip`).
- **Task 3.2:** Implement entity detail `GET /api/v1/graph/entity/{entity_id}` with incoming/outgoing relationships.
- **Task 3.3:** Add file-level graph exploration `GET /api/v1/graph/file/dependencies`.
- **Task 3.4:** Optimize overview query in Neo4j to avoid Cartesian explosion and label dead-code candidate detection as heuristic.
- **Task 3.5:** Write integration tests in `tests/test_graph_extended.py`.

## Phase 4: Production Configuration, Complete Documentation & Final Report (Stage 4.6 - 4.9 & 12)
- **Task 4.1:** Production startup validation (fail-fast on missing mandatory configs/secrets).
- **Task 4.2:** Create comprehensive documentation:
  - `README.md`
  - `docs/API_CONTRACT.md`
  - `docs/ARCHITECTURE.md`
  - `docs/DATABASE_SCHEMA.md`
  - `docs/NEO4J_GRAPH_SCHEMA.md`
  - `docs/ANALYSIS_PIPELINE.md`
  - `docs/SECURITY.md`
- **Task 4.3:** Run complete regression test suite and compile `docs/PRE_STAGE_5_COMPLETION_REPORT.md`.
