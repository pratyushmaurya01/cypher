# API Contract: Cypher Code Intelligence Platform (v1)

Base URL: `/api/v1`

All responses are serialized as JSON unless otherwise noted.

---

## Authentication & Authorization

All authenticated endpoints require an `Authorization` header:
```http
Authorization: Bearer <access_token>
```

When `APP_ENV=development` and `ALLOW_ANONYMOUS_DEV_ACCESS=true`, requests without an `Authorization` header will fall back to the built-in development owner account (`user_dev_001`). In `APP_ENV=production`, anonymous access is strictly disabled and returns `HTTP 401 Unauthorized`.

---

## 1. Authentication Endpoints

### Register User
- **POST** `/auth/signup`
- **Request Body:**
  ```json
  {
    "email": "user@example.com",
    "password": "strongpassword123"
  }
  ```
- **Responses:**
  - `201 Created`:
    ```json
    {
      "id": "usr_94a737f52dd242e88a0b0d662c1453bf",
      "email": "user@example.com",
      "created_at": "2026-11-14T12:00:00Z"
    }
    ```
  - `400 Bad Request`: Email already registered or invalid input format.

### User Login
- **POST** `/auth/login`
- **Request Body:**
  ```json
  {
    "email": "user@example.com",
    "password": "strongpassword123"
  }
  ```
- **Responses:**
  - `200 OK`:
    ```json
    {
      "access_token": "eyJhbGciOi...",
      "token_type": "bearer"
    }
    ```
  - `401 Unauthorized`: Invalid email or password.

### Current User Profile
- **GET** `/auth/me`
- **Headers:** `Authorization: Bearer <token>`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "id": "usr_94a737f52dd242e88a0b0d662c1453bf",
      "email": "user@example.com",
      "created_at": "2026-11-14T12:00:00Z"
    }
    ```
  - `401 Unauthorized`: Missing or invalid token.

---

## 2. Health & Status

### System Health
- **GET** `/health`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "status": "healthy",
      "version": "0.1.0",
      "neo4j_connected": true,
      "relational_db_connected": true
    }
    ```

---

## 3. Repository Management

### Upload Repository (ZIP)
- **POST** `/repository/upload`
- **Headers:** `Authorization: Bearer <token>`
- **Content-Type:** `multipart/form-data`
- **Form Parameters:**
  - `file`: ZIP file upload (streaming validation enforced).
  - `name`: *(Optional)* Display name of repository. Defaults to archive filename.
- **Enforced Upload Security Checks:**
  - Maximum upload size (50MB) streaming cut-off (`413 Content Too Large`).
  - Strict ZIP header validation.
  - Path traversal and symlink prevention (`422 Unprocessable Content`).
  - Max archive file count limit (10,000 files).
  - Max total uncompressed size limit (250MB).
  - Compression bomb ratio rejection (> 100.0).
  - Nested archive rejection (`.zip`, `.tar`, `.gz`, etc.).
- **Responses:**
  - `201 Created`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "name": "my-project",
      "status": "pending",
      "version": 1,
      "message": "Repository uploaded and snapshot staged. Ready for analysis."
    }
    ```
  - `413 Content Too Large`: Payload exceeds size limit.
  - `422 Unprocessable Content`: Malformed archive, path traversal, or ZIP bomb detected.

### List User Repositories
- **GET** `/repository/list`
- **Headers:** `Authorization: Bearer <token>`
- **Responses:**
  - `200 OK`:
    ```json
    [
      {
        "repository_id": "repo_e4b162540b61",
        "owner_id": "usr_94a737f52dd242e88a0b0d662c1453bf",
        "name": "my-project",
        "status": "ready",
        "snapshot_version": 1,
        "created_at": "2026-11-14T12:05:00Z",
        "updated_at": "2026-11-14T12:05:30Z"
      }
    ]
    ```

### Start Repository Analysis
- **POST** `/repository/analyze`
- **Headers:** `Authorization: Bearer <token>`
- **Request Body:**
  ```json
  {
    "repository_id": "repo_e4b162540b61"
  }
  ```
- **Responses:**
  - `202 Accepted`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "status": "ready",
      "message": "Repository analysis completed successfully."
    }
    ```
  - `404 Not Found`: Repository not found or not owned by user.

### Check Analysis Status
- **GET** `/repository/{repository_id}/status`
- **Headers:** `Authorization: Bearer <token>`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "status": "ready",
      "error_message": null,
      "updated_at": "2026-11-14T12:05:30Z"
    }
    ```
  - `404 Not Found`: Repository not found or access denied.

### Delete Repository (Complete Lifecycle Cascading)
- **DELETE** `/repository/{repository_id}`
- **Headers:** `Authorization: Bearer <token>`
- **Operations executed:**
  1. Detach & deletes all repository nodes & edges from Neo4j graph.
  2. Removes repository record from PostgreSQL metadata database.
  3. Deletes on-disk snapshot and storage directory tree.
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "deleted": true,
      "message": "Repository, code graph, and disk snapshots deleted successfully."
    }
    ```
  - `403 Forbidden` / `404 Not Found`: Cross-user deletion attempt or missing repo.

---

## 4. Graph Exploration & Intelligence Endpoints

### Repository Graph Overview
- **GET** `/graph/overview?repository_id={repository_id}`
- **Headers:** `Authorization: Bearer <token>`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "total_modules": 12,
      "total_classes": 24,
      "total_functions": 110,
      "total_calls": 340,
      "total_routes": 15
    }
    ```

### Filtered & Paginated Entity Discovery
- **GET** `/graph/entities?repository_id={repository_id}&kind={kind}&file_path={file_path}&limit={limit}&offset={offset}`
- **Headers:** `Authorization: Bearer <token>`
- **Query Parameters:**
  - `repository_id` (required, string)
  - `kind` (optional, string: `"function"`, `"class"`, or `"module"`)
  - `file_path` (optional, string: exact or prefix file path)
  - `limit` (optional, int, default: 50, max: 1000)
  - `offset` (optional, int, default: 0)
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "total": 42,
      "limit": 50,
      "offset": 0,
      "entities": [
        {
          "id": "repo_e4b162540b61:auth.py:verify_password",
          "name": "verify_password",
          "qualified_name": "auth.verify_password",
          "kind": "function",
          "file_path": "auth.py",
          "start_line": 25,
          "end_line": 32,
          "docstring": "Verify hashed password."
        }
      ]
    }
    ```

### Detailed Entity Inspection (with Edges)
- **GET** `/graph/entity/{entity_id}?repository_id={repository_id}`
- **Headers:** `Authorization: Bearer <token>`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "id": "repo_e4b162540b61:auth.py:verify_password",
      "name": "verify_password",
      "qualified_name": "auth.verify_password",
      "kind": "function",
      "file_path": "auth.py",
      "start_line": 25,
      "end_line": 32,
      "docstring": "Verify hashed password.",
      "incoming_edges": [
        {
          "relationship": "CALLS",
          "source_id": "repo_e4b162540b61:routes.py:login",
          "source_name": "login",
          "source_kind": "function"
        }
      ],
      "outgoing_edges": []
    }
    ```
  - `404 Not Found`: Entity not found in repository.

### File Dependency Discovery
- **GET** `/graph/file/dependencies?repository_id={repository_id}&file_path={file_path}`
- **Headers:** `Authorization: Bearer <token>`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "file_path": "auth.py",
      "imports": ["hashlib", "os"],
      "imported_by": ["main.py", "api/routes.py"]
    }
    ```

### Query Call Hierarchy
- **GET** `/graph/call-hierarchy?repository_id={repository_id}&function_name={function_name}&direction={both|incoming|outgoing}&depth={depth}`
- **Query Parameters:**
  - `direction`: `"incoming"` (callers), `"outgoing"` (callees), or `"both"` (default).
  - `depth`: Integer between 1 and 5 (default: 2).

### Circular Dependencies
- **GET** `/graph/circular-dependencies?repository_id={repository_id}`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "cycles": [
        ["module_a", "module_b", "module_a"]
      ]
    }
    ```

### Dead Code Candidates
- **GET** `/graph/dead-code?repository_id={repository_id}`
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "candidates": [
        {
          "qualified_name": "utils.unused_helper",
          "kind": "function",
          "file_path": "utils.py",
          "start_line": 40,
          "end_line": 45,
          "confidence": "high",
          "reason": "No incoming internal calls detected.",
          "heuristic_notes": "Static graph heuristic: dynamic or external call sites cannot be detected via static analysis."
        }
      ]
    }
    ```

---

## 5. Source Code Retrieval Endpoints

### Retrieve Entire File
- **GET** `/source/file?repository_id={repository_id}&file_path={file_path}`
- **Headers:** `Authorization: Bearer <token>`
- **Safety Enforcement:**
  - Canonical path resolution against persistent repository snapshot directory.
  - Rejection of directory traversal (`..`, absolute paths, symlinks).
  - Maximum size restriction (2MB default).
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "file_path": "main.py",
      "content": "from fastapi import FastAPI\n...",
      "total_lines": 45,
      "size_bytes": 1024
    }
    ```
  - `400 Bad Request`: Directory traversal attempt.
  - `404 Not Found`: File or repository not found.
  - `413 Content Too Large`: File exceeds size limit.

### Retrieve Code Range
- **GET** `/source/range?repository_id={repository_id}&file_path={file_path}&start_line={start}&end_line={end}`
- **Headers:** `Authorization: Bearer <token>`
- **Query Parameters:**
  - `start_line` (int, 1-indexed)
  - `end_line` (int, 1-indexed, `end_line >= start_line`, max range 1000 lines)
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "file_path": "main.py",
      "start_line": 10,
      "end_line": 20,
      "content": "def create_app():\n    app = FastAPI()\n    return app\n",
      "total_lines": 11
    }
    ```

### Retrieve AST Symbol
- **GET** `/source/symbol?repository_id={repository_id}&symbol_name={name}&file_path={optional_file_path}`
- **Headers:** `Authorization: Bearer <token>`
- **Resolution Strategy:**
  1. Neo4j graph AST line range lookup.
  2. Fallback to precise in-memory AST line range extraction directly from snapshot source if graph is not yet populated.
- **Responses:**
  - `200 OK`:
    ```json
    {
      "repository_id": "repo_e4b162540b61",
      "symbol_name": "create_app",
      "file_path": "main.py",
      "start_line": 10,
      "end_line": 20,
      "content": "def create_app():\n    app = FastAPI()\n    return app\n",
      "kind": "function"
    }
    ```
  - `404 Not Found`: Symbol not found.
