# Pre-Stage 5 Comprehensive Codebase & Architecture Audit
**Cypher — Code Intelligence Platform**  
*Date:* November 14, 2026  
*Status:* Pre-Stage 5 Initial Inspection Complete

---

## 1. Executive Summary & Existing Architecture

Cypher is a static-analysis-driven Code Intelligence and Knowledge Graph backend. The architecture is composed of six distinct functional layers:

1. **AST Parser & Extraction Layer (`cypher/analyzer/`):**
   - AST file discovery and parsing (`ast_parser.py`).
   - Function & class extraction, async functions, decorators, method tracking.
   - Imports extraction (`imports.py`), function call extraction (`function_calls.py`), URL route pattern extraction (`url_extractor.py`).
2. **Cross-File Resolution & Symbol Graph Layer (`cypher/resolver/`):**
   - Global symbol indexing (`symbol_index.py`).
   - Import resolution with scope & alias handling (`import_resolver.py`).
   - Call graph resolution with class method & instance receiver resolution (`call_resolver.py`).
   - Web framework route resolution for Django, FastAPI, and Flask (`django_url_resolver.py`, `fastapi_resolver.py`, `flask_resolver.py`).
   - Relationship validation and graph structure generation (`relationship_builder.py`).
3. **Graph Ingestion & Cypher Storage Layer (`cypher/graph/`):**
   - Neo4j driver client with schema constraint initialization (`neo4j_client.py`).
   - Parameterized batch payload builder and idempotent `MERGE` ingestion (`graph_builder.py`).
   - Domain-specific Cypher query templates (`queries.py`).
4. **Relational Database & Authentication Layer (`cypher/db/`, `cypher/core/`):**
   - SQLAlchemy 2.0 models (`User`, `RepositoryMetadata`).
   - Password hashing with bcrypt, JWT token creation and validation (`security.py`).
5. **Physical Source Code Snapshot & Retrieval Layer (`cypher/services/`):**
   - Versioned immutable disk snapshots (`snapshots/v1/`, `snapshots/v2/`, `current/`) in `source_code_service.py`.
   - Path traversal and symlink escape prevention.
   - Lexical scope tracking for AST symbol definition fallback.
   - Retrieval size limits (max 2 MB per file, max 1,000 lines per range).
6. **FastAPI Web API Layer (`cypher/api/`):**
   - `/api/v1/health` (connectivity checks for service and Neo4j).
   - `/api/v1/auth` (signup, login, user profile).
   - `/api/v1/repository` (upload ZIP & analyze, list my repositories, get repository details).
   - `/api/v1/graph` (overview, routes, function callers/dependencies, module dependencies, class hierarchy, dead code).
   - `/api/v1/source` (get full file, get line range, get symbol source).

---

## 2. Completed Functionality

- **AST Parsing & Static Analysis Engine:**
  - Robust scanning supporting syntax error isolation (does not halt repository scan).
  - Accurate extraction of functions, async functions, classes, methods, imports, and calls.
  - Multi-framework web routing detection (Django `path`/`include`, FastAPI `APIRouter`/`include_router`, Flask Blueprints).
  - Referential integrity validation avoiding broken dangling relationship references.
- **Neo4j Graph Building:**
  - Idempotent parameterized batch ingestion (`UNWIND $batch AS item MERGE ...`).
  - Label constraints on `Entity(id)` and `Repository(id)`.
  - Scoped deletion and repository isolation (`MATCH (r:Repository {id: $repo_id}) DETACH DELETE r`).
- **PostgreSQL / SQLAlchemy Storage:**
  - Users with bcrypt hashed passwords and JWT access token issuance.
  - Ownership isolation for repository metadata.
- **Source Code Hardening (Stage 4.1):**
  - Deterministic repository IDs derived from `(owner_id, repo_name)`.
  - Versioned immutable snapshots under `snapshots/v{version}/`.
  - Path traversal & symlink escape detection using `Path.is_relative_to()`.
  - Lexical scope AST fallback symbol search.
  - Pre-ingestion ownership validation.
  - Production authentication enforcement (`effective_allow_anonymous_dev`).
- **Test Suite Status:**
  - 120/120 tests passing in `tests/`.

---

## 3. Incomplete Functionality & Gaps Identified

1. **Database Migrations (Alembic):**
   - No Alembic configuration (`alembic.ini` or migration versions directory) exists in the repository.
   - Schema currently relies solely on runtime `Base.metadata.create_all(bind=engine)` via `init_db()`.
   - Existing databases cannot be upgraded cleanly when fields (like `current_version`) are added.
2. **Repository Lifecycle & Deletion APIs:**
   - There is currently **no `DELETE /api/v1/repository/{repository_id}` endpoint**.
   - Deleting a repository must atomically or cleanly:
     - Delete graph nodes in Neo4j (`MATCH (r:Repository {id: $repo_id}) OPTIONAL MATCH (n:Entity {repository_id: $repo_id}) DETACH DELETE n, r`).
     - Remove disk snapshot storage (`storage/repositories/{owner_id}/{repo_id}`).
     - Delete the `RepositoryMetadata` record in PostgreSQL.
3. **Graph Query & Retrieval Depth (Stage 4.5):**
   - Predefined queries lack entity listing (`GET /api/v1/graph/entities`), entity detail lookup (`GET /api/v1/graph/entity/{entity_id}`), and file-level graph inspection.
   - Graph endpoints lack query pagination / limits, which may cause large JSON payloads for repositories with thousands of nodes.
4. **Upload Security & Streaming Validation:**
   - `upload_and_analyze` currently reads the entire ZIP into memory with `await file.read()` before checking total archive size.
   - While max byte checks exist after reading, archives should be inspected for zip bomb indicators (uncompressed extraction size ratio, file count > 10,000).
5. **Atomic Staging and Promotion for Snapshots:**
   - If an upload fails during AST analysis or Neo4j ingestion, a snapshot version folder has already been created on disk. A rollback/cleanup staging routine should safely clean uncommitted snapshot stages.
6. **Documentation Deficits:**
   - Root `README.md` is empty (0 bytes).
   - Core specifications (`docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/DATABASE_SCHEMA.md`, `docs/NEO4J_GRAPH_SCHEMA.md`, `docs/ANALYSIS_PIPELINE.md`, `docs/SECURITY.md`) are missing or unwritten.

---

## 4. Confirmed Bugs & Security Risks

1. **Alembic Missing (High Operational Risk):** Without Alembic, production PostgreSQL schema changes risk downtime or manual table patching.
2. **Missing Repository Deletion (Lifecycle Risk):** Users cannot delete obsolete or erroneous repository scans; orphaned disk files and Neo4j nodes accumulate.
3. **Streaming In-Memory Upload Risk (Denial of Service):** Reading entire file into RAM before size assertion can be abused if large payloads bypass proxy limits.
4. **Neo4j Overview Query Null Handling:** In `REPOSITORY_OVERVIEW_QUERY`, if no modules or functions exist, counts might return 0, but multiple `OPTIONAL MATCH` clauses without Cartesian product precautions could lead to Cartesian explosion on repositories with thousands of entities.

---

## 5. Missing Test Coverage

- Repository deletion test (PostgreSQL + Neo4j + disk snapshot removal).
- Alembic upgrade/downgrade migration test.
- Atomic upload failure rollback test (ensuring failed ingestion leaves no orphaned uncommitted snapshot).
- Malformed archive and zip bomb protection tests.
- Paginated entity listing and entity detail graph API tests.

---

## 6. Recommended Implementation Roadmap (Stages 4.1 to 4.9)

### Phase 1: Storage, Upload & Atomic Staging Hardening (Stage 4.1 Completion)
- Streaming upload size check & zip bomb defense (uncompressed size/count limits).
- Atomic staging for snapshots: stage in `.staging_v{version}`, promote to `v{version}` only upon successful DB & Neo4j ingestion; clean up staging on failure.

### Phase 2: Database Migration & Lifecycle Reliability (Stage 4.2 & 4.7)
- Initialize Alembic with migration versions (`0001_initial_schema.py`).
- Implement repository deletion service & endpoint `DELETE /api/v1/repository/{repository_id}` handling PostgreSQL, Neo4j, and disk cleanup.
- Add transaction rollback handling on upload/analysis failures.

### Phase 3: Complete Analysis Engine & Graph Retrieval APIs (Stage 4.3, 4.4 & 4.5)
- Enhance graph endpoints:
  - Add entity listing (`GET /api/v1/graph/entities` with filtering by kind/file).
  - Add entity detail (`GET /api/v1/graph/entity/{entity_id}`).
  - Add incoming/outgoing relationship exploration.
  - Add pagination parameters (`limit`, `skip`).

### Phase 4: Production Configuration, Contracts & Documentation (Stage 4.6, 4.8, 4.9 & 12)
- Fast-fail configuration check on startup in production.
- Generate `docs/API_CONTRACT.md`, `docs/ARCHITECTURE.md`, `docs/DATABASE_SCHEMA.md`, `docs/NEO4J_GRAPH_SCHEMA.md`, `docs/ANALYSIS_PIPELINE.md`, `docs/SECURITY.md`, and populate `README.md`.
- Compile final `docs/PRE_STAGE_5_COMPLETION_REPORT.md`.
