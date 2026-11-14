# Neo4j Knowledge Graph Schema

Cypher builds and persists an interconnected property graph representing the structural semantics of Python source code repositories.

---

## 1. Graph Model & Topology

Nodes represent structural programming entities (Modules, Classes, Functions, Routes, External Dependencies), while edges model semantic relationships (Containment, Calls, Inheritance, Imports, HTTP Routing).

```
   (:Repository)
        |
    [CONTAINS]
        v
    (:Module) --------[IMPORTS]--------> (:ExternalDependency)
      |    \
 [DEFINES] [DEFINES]
    v        v
(:Class)  (:Function) ------------------> (:Function)
    |          |            [CALLS]
[INHERITS] [ROUTES_TO]
    v          v
(:Class)    (:Route)
```

---

## 2. Node Labels and Properties

### 2.1 `(:Repository)`
Root node representing an uploaded code repository.
- `id` *(string, unique)*: Deterministic repository ID (e.g. `repo_a1b2c3d4e5f6`).
- `name` *(string)*: Human-readable name.
- `version` *(string/int)*: Snapshot version.

### 2.2 `(:Module)`
Represents an individual Python source file (`.py`).
- `id` *(string, unique)*: `{repository_id}:{file_path}`
- `name` *(string)*: Module name (e.g. `main`, `config`).
- `file_path` *(string)*: Relative file path within repository.
- `repository_id` *(string)*: Tenant isolation key.

### 2.3 `(:Class)`
Represents an object-oriented class definition.
- `id` *(string, unique)*: `{repository_id}:{file_path}:{class_name}`
- `name` *(string)*: Class identifier.
- `qualified_name` *(string)*: Full module-qualified name (e.g. `cypher.services.SourceCodeService`).
- `file_path` *(string)*: Source file path.
- `start_line` *(int)*: Beginning line number in source.
- `end_line` *(int)*: Ending line number in source.
- `docstring` *(string, optional)*: Docstring content.
- `repository_id` *(string)*: Tenant isolation key.

### 2.4 `(:Function)`
Represents standalone functions, nested functions, and class methods.
- `id` *(string, unique)*: `{repository_id}:{file_path}:{function_name}`
- `name` *(string)*: Function or method name.
- `qualified_name` *(string)*: Full lexical path (e.g. `cypher.api.routes.api_router`).
- `file_path` *(string)*: Source file path.
- `start_line` *(int)*: Beginning line number in source.
- `end_line` *(int)*: Ending line number in source.
- `is_async` *(boolean)*: True if declared with `async def`.
- `docstring` *(string, optional)*: Docstring content.
- `parameters` *(list of strings)*: Parameter names and type signatures.
- `return_type` *(string, optional)*: Return type annotation.
- `repository_id` *(string)*: Tenant isolation key.

### 2.5 `(:ExternalDependency)`
Represents imported third-party or standard library packages.
- `id` *(string, unique)*: Package name (e.g. `fastapi`, `sqlalchemy`).
- `name` *(string)*: Package name.

### 2.6 `(:Route)`
Represents exposed HTTP API endpoints detected from web frameworks (FastAPI / Flask).
- `id` *(string, unique)*: `{repository_id}:{method}:{path}`
- `path` *(string)*: URL route pattern (e.g. `/api/v1/health`).
- `method` *(string)*: HTTP verb (`GET`, `POST`, `PUT`, `DELETE`).
- `framework` *(string)*: Detected framework (`fastapi` or `flask`).
- `repository_id` *(string)*: Tenant isolation key.

---

## 3. Relationship Types

| Relationship | Source Node | Target Node | Description |
| :--- | :--- | :--- | :--- |
| `CONTAINS` | `Repository` | `Module` | Hierarchical ownership of a module by a repository. |
| `DEFINES` | `Module` | `Class` / `Function` | Symbol defined within the module scope. |
| `DEFINES` | `Class` | `Function` | Method defined within the class scope. |
| `CALLS` | `Function` | `Function` | Function or method invoking another function. |
| `INHERITS` | `Class` | `Class` | Subclass inheriting from a base class. |
| `IMPORTS` | `Module` | `ExternalDependency` / `Module` | Source module importing a library or internal file. |
| `ROUTES_TO` | `Route` | `Function` | HTTP endpoint dispatched to a handler function. |

---

## 4. Graph Constraints and Performance Indices

Neo4j indexing ensures fast lookups and protects against duplicate entities:

```cypher
CREATE CONSTRAINT FOR (r:Repository) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT FOR (m:Module) REQUIRE m.id IS UNIQUE;
CREATE CONSTRAINT FOR (c:Class) REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT FOR (f:Function) REQUIRE f.id IS UNIQUE;
CREATE CONSTRAINT FOR (e:ExternalDependency) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT FOR (rt:Route) REQUIRE rt.id IS UNIQUE;

CREATE INDEX FOR (m:Module) ON (m.repository_id);
CREATE INDEX FOR (c:Class) ON (c.repository_id);
CREATE INDEX FOR (f:Function) ON (f.repository_id);
```

---

## 5. Query Optimization & Cartesian Prevention

To prevent Cartesian product explosions during repository graph overviews, queries avoid joining across multiple un-aggregated `OPTIONAL MATCH` clauses. Sequential `WITH` aggregations collapse row cardinalities into sub-totals:

```cypher
MATCH (r:Repository {id: $repository_id})
OPTIONAL MATCH (r)-[:CONTAINS]->(m:Module)
WITH r, count(DISTINCT m) AS total_modules
OPTIONAL MATCH (r)-[:CONTAINS]->(:Module)-[:DEFINES*1..2]->(c:Class)
WITH r, total_modules, count(DISTINCT c) AS total_classes
OPTIONAL MATCH (r)-[:CONTAINS]->(:Module)-[:DEFINES*1..2]->(f:Function)
WITH r, total_modules, total_classes, count(DISTINCT f) AS total_functions
OPTIONAL MATCH (f:Function {repository_id: $repository_id})-[rel:CALLS]->()
WITH r, total_modules, total_classes, total_functions, count(rel) AS total_calls
OPTIONAL MATCH (rt:Route {repository_id: $repository_id})
RETURN r.id AS repository_id,
       total_modules,
       total_classes,
       total_functions,
       total_calls,
       count(DISTINCT rt) AS total_routes;
```
