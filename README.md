# Cypher — Python Code Intelligence & Knowledge Graph Platform

Cypher is a high-performance backend platform that parses Python repositories using purely static analysis (Abstract Syntax Tree), resolves complex structural and semantic code relationships, and models them as an interconnected knowledge graph in Neo4j. It provides secure multi-tenant repository management, versioned snapshot storage, source code retrieval, and graph exploration APIs.

---

## Key Features

- **Static AST Code Intelligence**:
  - Full structural parsing without executing untrusted code.
  - Extracts modules, classes, methods, standalone functions, closures, decorators, parameter type annotations, and docstrings.
  - Resolves internal and external package imports.
  - Generates cross-module and intra-class call graphs.
  - Resolves object-oriented class inheritance trees.
  - Detects web framework HTTP routes for FastAPI and Flask endpoints.

- **Neo4j Property Graph**:
  - Highly optimized graph storage with unique constraints and indices.
  - Query call hierarchies (callers, callees, bidirectional depth exploration).
  - Detect circular module dependencies.
  - Heuristic dead-code candidate detection.
  - High-performance overview queries engineered to prevent Cartesian product row explosions.

- **Enterprise Security & Multi-Tenancy**:
  - JWT (JSON Web Token) authentication with hashed password storage.
  - Owner-isolated repositories and deterministic repository identity.
  - Complete cross-tenant authorization enforcement across PostgreSQL, Neo4j, and the filesystem.
  - Production fail-fast startup validations for secrets and database configurations.

- **Hardened Archive Ingestion & Source Storage**:
  - Streaming HTTP upload cutoff to prevent memory buffer exhaustion.
  - 4-tier ZIP bomb defense (file count, uncompressed size limit, compression ratio, nested archive rejection).
  - Path traversal and symlink attack prevention with canonical path sandbox enforcement.
  - Two-phase atomic staging and promotion for versioned, immutable snapshot directories.

- **Source Code Retrieval**:
  - Direct retrieval of full source files, bounded line ranges, or AST symbols.
  - Fallback lexical AST resolution when Neo4j is offline or pending ingestion.
  - Exact preservation of indentation, comments, and file encodings.

---

## Architecture Overview

```
 [Client / Frontend]
         |
         v
 [FastAPI Gateway (v1)]
    ├── Auth & Users (PostgreSQL + Alembic)
    ├── Repository Lifecycle & Storage Service (Versioned Sandboxes)
    ├── Static Code Analysis Engine (AST Parser & Resolvers)
    └── Knowledge Graph Engine (Neo4j Property Graph)
```

For full architectural details, consult:
- [System Architecture](file:///C:/Users/praty/OneDrive/01projects/minor_project/docs/ARCHITECTURE.md)
- [API Contract](file:///C:/Users/praty/OneDrive/01projects/minor_project/docs/API_CONTRACT.md)
- [Relational Database Schema](file:///C:/Users/praty/OneDrive/01projects/minor_project/docs/DATABASE_SCHEMA.md)
- [Neo4j Graph Schema](file:///C:/Users/praty/OneDrive/01projects/minor_project/docs/NEO4J_GRAPH_SCHEMA.md)
- [Analysis Pipeline](file:///C:/Users/praty/OneDrive/01projects/minor_project/docs/ANALYSIS_PIPELINE.md)
- [Security Guide](file:///C:/Users/praty/OneDrive/01projects/minor_project/docs/SECURITY.md)

---

## Quickstart & Installation

### 1. Prerequisites
- Python 3.10+
- PostgreSQL (or local SQLite for dev/test)
- Neo4j 5.x+ (local Docker instance or Neo4j AuraDB)

### 2. Environment Setup
Clone the repository and set up a virtual environment:
```bash
git clone https://github.com/your-org/cypher.git
cd cypher

python -m venv .venv
# On Windows:
.\.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the project root:
```env
# Application Environment (development | production)
APP_ENV=development
ALLOW_ANONYMOUS_DEV_ACCESS=true

# Relational Database
DATABASE_URL=sqlite:///./cypher.db
# For production PostgreSQL:
# DATABASE_URL=postgresql://user:password@localhost:5432/cypher

# JWT Authentication
JWT_SECRET_KEY=cypher-insecure-development-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Neo4j Graph Database
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

# Storage Limits
STORAGE_DIR=./storage/repositories
MAX_UPLOAD_BYTES=52428800
MAX_SOURCE_FILE_BYTES=2097152
MAX_RANGE_LINES=1000
```

### 4. Database Migrations
Initialize or upgrade the relational database schema using Alembic:
```bash
alembic upgrade head
```

### 5. Running the Application
Start the development server with live reload:
```bash
uvicorn cypher.main:app --reload --host 0.0.0.0 --port 8000
```
Interactive OpenAPI documentation will be accessible at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

---

## Running the Test Suite

Run the complete test suite with `pytest`:
```bash
pytest tests/ -v
```
All 132 automated tests verify AST parsing, resolvers, Neo4j graphs, authentication, authorization, ZIP upload security, atomic staging, lifecycle deletion, and source code retrieval.

---

## Project Structure

```
cypher/
├── api/                  # FastAPI routers and endpoint controllers
│   ├── deps.py           # Dependency injection (Auth, Neo4j, DB)
│   ├── routes.py         # Root v1 router
│   └── v1/               # Versioned endpoint handlers
├── db/                   # Relational database models and session setup
├── graph/                # Neo4j client, query builder, and graph ingestion
├── parser/               # Static AST parser and visitor extraction
├── resolvers/            # Call, inheritance, import, and route resolvers
├── schemas/              # Pydantic v2 request/response models
├── services/             # Core business services (Analysis, SourceCode, Auth)
├── config.py             # Typed Pydantic application settings
└── main.py               # FastAPI application entry point and lifespan
alembic/                  # Database migration scripts
docs/                     # Comprehensive architecture and security documentation
storage/                  # Isolated, versioned repository snapshots
tests/                    # Automated unit, integration, and API tests
```
