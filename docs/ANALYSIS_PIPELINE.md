# Static Code Analysis Pipeline

The static code analysis pipeline in Cypher transforms raw Python source code into a structured, queryable knowledge graph. It parses files into Abstract Syntax Trees (AST), extracts structural metadata, resolves relationships, and builds ingestion payloads for Neo4j.

---

## 1. Pipeline Overview

```
 [Uploaded ZIP]
       |
       v
 [Safe Unpacking] ----> [Storage Snapshot v{version}]
                                |
                                v
                     [1. File Discovery] (.py files)
                                |
                                v
                     [2. AST Parsing] (ast.parse)
                                |
                                v
                     [3. Symbol Extraction] (Classes, Functions, Methods)
                                |
                                v
                     [4. Resolution Phase]
                        - Scope Resolution
                        - Call Graph Resolution
                        - Inheritance Resolution
                        - Route Resolution (FastAPI / Flask)
                                |
                                v
                     [5. Graph Payload Construction]
                                |
                                v
                     [6. Neo4j Batch Ingestion]
```

---

## 2. Stage Breakdown

### Stage 1: File Discovery & Filtering
- Scans the repository root directory recursively.
- Automatically ignores non-code directories: `.git`, `__pycache__`, `.venv`, `venv`, `node_modules`, `.tox`, `dist`, `build`.
- Discovers and buffers all valid `.py` source files.

### Stage 2: AST Parsing (`cypher/parser/ast_parser.py`)
- Reads file contents with robust UTF-8 and fallback encoding handlers.
- Parses code into an Abstract Syntax Tree using `ast.parse(source_code, filename=...)`.
- Generates `ModuleMetadata` tracking imports, docstrings, and syntax validation flags.

### Stage 3: Symbol Extraction
- Uses an AST Visitor (`ast.NodeVisitor`) to traverse module nodes.
- **Classes**:
  - Captures name, docstrings, line numbers (`start_line`, `end_line`), base class names, and decorators.
- **Functions & Methods**:
  - Distinguishes between standalone module functions and class methods.
  - Captures lexical name, qualified name, async flags, decorators, parameters with type annotations, return types, and docstrings.
  - Accurately tracks nested function and closure scopes.

### Stage 4: Semantic Relationship Resolution
- **Import Resolution (`cypher/resolvers/import_resolver.py`)**:
  - Resolves standard library imports, third-party packages, and internal relative/absolute imports to module IDs.
- **Call Resolution (`cypher/resolvers/call_resolver.py`)**:
  - Tracks `ast.Call` nodes.
  - Matches invocation expressions against known symbol definitions (handling direct calls, `self.method()`, and `module.function()`).
- **Inheritance Resolution (`cypher/resolvers/inheritance_resolver.py`)**:
  - Matches class inheritance bases against discovered class symbols to establish subclassing edges.
- **Web Route Resolution (`cypher/resolvers/route_resolver.py`)**:
  - Detects FastAPI (`@app.get()`, `@router.post()`) and Flask (`@app.route()`) decorators.
  - Extracts HTTP verbs, route URL templates, and connects them to the handling Python function.

### Stage 5: Ingestion Payload Generation (`cypher/graph/graph_builder.py`)
- Aggregates extracted entities and resolved edges.
- Formats dictionary payloads into structured Cypher batches with parameterized variables.
- Ensures all generated IDs incorporate the `repository_id` prefix for strong multi-tenant isolation.

### Stage 6: Neo4j Ingestion (`cypher/graph/neo4j_client.py`)
- Executes batch Cypher statements inside transactions.
- Uses idempotent `MERGE` statements on constrained keys to allow safe re-analysis without orphaned duplicate nodes.

---

## 3. Heuristics & Static Analysis Boundaries

- **Dynamic Invocations**: Python features such as `getattr(obj, "name")()`, `eval()`, or runtime monkey patching cannot be statically linked to destination functions.
- **Dead Code Detection**:
  - Identified when an internal function has zero incoming `CALLS` edges in the graph.
  - Marked with `confidence="high"` or `confidence="medium"` and labeled as a heuristic candidate because dynamic calls, tests, or external library consumers cannot be discovered statically.
