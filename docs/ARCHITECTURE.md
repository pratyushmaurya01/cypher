# Cypher System Architecture

Cypher is a static code intelligence and knowledge graph platform for Python repositories. It analyzes source code structure, dependencies, call hierarchies, inheritance trees, and web framework route mappings without executing arbitrary user code.

---

## 1. High-Level Architectural Diagram

```
                 +-------------------------------------------------+
                 |                FastAPI Gateway                  |
                 |          (CORS, Auth, Validation, Lifespan)     |
                 +-------------------------------------------------+
                                          |
                   +----------------------+----------------------+
                   |                                             |
                   v                                             v
       +-----------------------+                     +-----------------------+
       |   Relational DB       |                     |     Disk Storage      |
       |  (PostgreSQL/Alembic) |                     | (Versioned Snapshots) |
       |  - Users & Auth       |                     | - Safe ZIP Extraction |
       |  - Repo Metadata      |                     | - Atomic Staging      |
       |  - Version Tracking   |                     | - Source Retrieval    |
       +-----------------------+                     +-----------------------+
                   |
                   v
       +---------------------------------------------------------+
       |              Static Code Analysis Engine                |
       |  - AST Parsing (ast.parse, Visitor pattern)             |
       |  - Symbol Indexing (Modules, Classes, Functions)        |
       |  - Resolvers: Calls, Inheritance, Imports               |
       |  - Web Route Resolvers (FastAPI & Flask decorators)     |
       +---------------------------------------------------------+
                                   |
                                   v
                   +-------------------------------+
                   |      Neo4j Graph Database     |
                   | - Nodes: Repos, Modules,      |
                   |   Classes, Functions, Routes  |
                   | - Edges: CONTAINS, CALLS,     |
                   |   INHERITS, IMPORTS, etc.     |
                   | - Optimized Aggregation       |
                   +-------------------------------+
```

---

## 2. Component Layers

### 2.1 API & Presentation Layer (`cypher/api/`)
- Built on **FastAPI** with Pydantic v2 validation.
- Clean separation between routing, dependencies (`cypher/api/deps.py`), and business services.
- Versioned under `/api/v1` namespace.
- Sub-routers:
  - `auth.py`: User registration, JWT login, and `/me`.
  - `repository.py`: Upload, streaming verification, analysis triggering, status tracking, and deletion cascading.
  - `graph.py`: Code graph overview, entity discovery, entity edge inspection, call hierarchies, circular dependencies, dead code heuristics.
  - `source.py`: Pure source retrieval (entire files, bounded line ranges, AST symbols).
  - `health.py`: Liveness and dependency connectivity probes.

### 2.2 Relational Data Layer (`cypher/db/` & `alembic/`)
- SQLAlchemy 2.0 ORM with declarative mappings.
- **PostgreSQL** in production with seamless local SQLite fallback for testing.
- **Alembic** database migrations with automated batch mode enabled for cross-database schema evolution.
- Stores identity, authentication credentials, and repository ownership state.

### 2.3 Storage & Staging Service (`cypher/services/source_code_service.py`)
- Manages repository code archives and extracted snapshots.
- **Atomic Two-Phase Staging**: Uploads are initially extracted and validated inside `.staging_{token}` folders. Once verified, they are atomically promoted to versioned snapshot folders (`v{version}/repo_name`).
- Strictly isolated by user and repository ID: `storage/repositories/{owner_id}/{repository_id}/v{version}/`.
- Guarantees read immutability and protects source retrieval against path traversal, symlink spoofing, and file size overflow.

### 2.4 Static Analysis Pipeline (`cypher/parser/` & `cypher/resolvers/`)
- Purely static parsing using Python's standard `ast` library.
- Extracts lexical scopes, docstrings, decorators, parameters, type annotations, and line ranges.
- Multi-pass resolution:
  - Scope resolution for functions and classes.
  - Call resolution matching invocations to definitions.
  - Inheritance resolution tracking base classes.
  - Framework route detection for FastAPI and Flask endpoints.

### 2.5 Graph Intelligence Layer (`cypher/graph/`)
- Property graph stored in **Neo4j** queried via parameterized Cypher statements.
- `Neo4jClient`: Thread-safe driver wrapping connection pooling, retries, and session lifecycle.
- `GraphBuilder`: Batch builds graph payloads containing nodes and edges for high-throughput ingestion with idempotent `MERGE` constraints.
- `queries.py`: Optimized queries preventing Cartesian product explosions using sequential `WITH` aggregation clauses.

---

## 3. Data Flow: Repository Upload to Graph Ingestion

1. **Upload & Streaming Validation**:
   - The user streams a ZIP archive to `/api/v1/repository/upload`.
   - The streaming loop tracks bytes and enforces `MAX_UPLOAD_BYTES` (50MB) immediately.
2. **Multi-tier Archive Inspection**:
   - ZIP headers verified.
   - Total file count checked (`<= 10,000`).
   - Total uncompressed size checked (`<= 250MB`).
   - Compression ratio verified (`<= 100.0`).
   - Nested archives rejected.
3. **Staging & Promotion**:
   - Archive extracted into an ephemeral staging directory.
   - Repository identity generated deterministically (`repo_{hash(owner_id + name)}`).
   - Staged folder atomically moved to `v1` (or incremented version).
   - Metadata recorded in PostgreSQL with status `pending`.
4. **Analysis Execution**:
   - Triggered via `/api/v1/repository/analyze`.
   - AST parser walks all `.py` files in the snapshot.
   - Relationship resolvers build call, import, and route topologies.
   - `GraphBuilder` transforms metadata into Cypher batches.
   - `Neo4jClient` commits graph nodes and relationships.
   - Status updated to `ready` in PostgreSQL.
