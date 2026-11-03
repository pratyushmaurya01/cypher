# Cypher — Neo4j AuraDB Setup & Operations Guide

## 1. Overview
Cypher uses **Neo4j AuraDB (Enterprise Cloud)** to store AST-derived code knowledge graphs.

### Architecture
```
Python Source Code
       │
       ▼
[AST Parser (ast_parser.py)]
       │
       ▼
[Resolvers (Imports, Calls, URLs, Frameworks)]
       │
       ▼
[Graph-Ready JSON (RelationshipBuilder)]
       │
       ▼
[Neo4jClient & GraphBuilder]
       │
       ▼
(Neo4j AuraDB Cloud Instance)
```

---

## 2. Environment Variables

Store these variables in a local `.env` file at the project root:

```env
# Official Neo4j connection URI (use neo4j+s:// or neo4j+ssc:// for custom/cloud SSL)
NEO4J_URI=neo4j+ssc://<instance-id>.databases.neo4j.io

# AuraDB database username
NEO4J_USER=<instance-id>

# AuraDB user password
NEO4J_PASSWORD=<your-strong-password>

# Database name (AuraDB Free instances match the instance-id)
NEO4J_DATABASE=<instance-id>
```

> **Security Note**: Never commit `.env` to Git. `.gitignore` is pre-configured to exclude `.env`. Refer to `.env.example` for the template.

---

## 3. Schema & Constraints

`Neo4jClient.init_schema()` automatically creates unique constraints and indexes upon ingestion:

```cypher
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT repo_id_unique IF NOT EXISTS FOR (r:Repository) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT module_id_unique IF NOT EXISTS FOR (m:Module) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT class_id_unique IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT function_id_unique IF NOT EXISTS FOR (f:Function) REQUIRE f.id IS UNIQUE;
CREATE CONSTRAINT ext_id_unique IF NOT EXISTS FOR (x:ExternalDependency) REQUIRE x.id IS UNIQUE;
CREATE INDEX entity_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.name);
CREATE INDEX entity_qual_idx IF NOT EXISTS FOR (e:Entity) ON (e.qualified_name);
```

---

## 4. Multi-Repository Isolation & Idempotency

- Every entity node has `repository_id` attached.
- Repeated imports use `MERGE (n:Entity {id: item.id})` with parameterized `UNWIND $batch AS item` to ensure **100% idempotent ingestion without duplicates**.
- Calling `GraphBuilder.ingest(..., clear_existing_repo=True)` deletes only the nodes belonging to the target repository (`n.repository_id == $repo_id`) without affecting other repositories or shared external dependencies.

---

## 5. Verification Commands

### Run Offline Test Suite (58 Tests)
```powershell
python -m pytest tests/ -v
```

### Run Static Analysis + Dry-Run & Live AuraDB Ingestion
```powershell
# Dry run verification (no live DB required)
python check_analysis.py

# Live ingestion into AuraDB
python check_analysis.py --neo4j
```

---

## 6. Graph Query Examples

Available via `cypher.graph.queries`:

```python
from cypher.graph.neo4j_client import Neo4jClient
from cypher.graph.queries import (
    find_function_dependencies,
    find_function_callers,
    find_all_routes,
    get_repository_overview
)

client = Neo4jClient()

# 1. Trace function dependency chain
deps = find_function_dependencies(client, "users.views.user_list")
# -> users.services.list_users (depth: 1)
# -> users.repository.list_users (depth: 2)

# 2. Reverse call hierarchy
callers = find_function_callers(client, "users.repository.list_users")

# 3. All API Routes (Django, FastAPI, Flask)
routes = find_all_routes(client)

# 4. Repository overview statistics
overview = get_repository_overview(client)
```
