# Security & Multi-Tenancy Architecture

Security and isolation are core design requirements in the Cypher platform. Cypher analyzes untrusted user-uploaded code while guaranteeing host protection, data privacy, and multi-tenant resource boundaries.

---

## 1. Authentication & Access Control

### 1.1 JWT Bearer Tokens
- User sessions are governed by JSON Web Tokens signed with HMAC-SHA256 (`HS256`).
- Expiration is strictly enforced via the `exp` claim (default: 24 hours).
- Passwords are encrypted before persistence using Argon2 / Bcrypt cryptographic password hashing. Plaintext passwords are never stored or logged.

### 1.2 Multi-Tenant Repository Ownership
- Every repository is owned by a specific `owner_id`.
- The repository identifier is computed deterministically as:
  ```python
  repo_id = f"repo_{hashlib.sha256(f'{owner_id}:{repo_name}'.encode()).hexdigest()[:12]}"
  ```
- All repository mutations (`analyze`, `delete`), graph queries (`overview`, `entities`, `dead-code`), and source file retrieval operations require active authorization:
  - If a user attempts to access a repository owned by another user, the API immediately rejects the request with `HTTP 403 Forbidden` (or `HTTP 404 Not Found`).

### 1.3 Production Enforcement Mode
- When `APP_ENV=production`:
  - Default development keys (`cypher-insecure-development-secret-key...`) cause an immediate server startup crash.
  - SQLite is rejected at startup; PostgreSQL is required.
  - Anonymous fallback access is completely disabled. Requests without valid JWT headers are rejected with `HTTP 401 Unauthorized`.
  - Detailed internal Python tracebacks are suppressed in HTTP responses.

---

## 2. Archive Upload & ZIP Bomb Defenses

To defend against malicious archives and Denial of Service (DoS) attacks, upload handling employs a 4-tier verification protocol:

1. **Streaming HTTP Chunk Limiter**:
   - The upload endpoint reads incoming files in 64KB chunks up to `MAX_UPLOAD_BYTES` (50MB).
   - If an upload exceeds this threshold, the connection is aborted immediately with `HTTP 413 Content Too Large` without buffering the remainder to disk or RAM.
2. **File Count Throttling**:
   - The archive is inspected prior to extraction. Archives containing more than `10,000` files are rejected with `HTTP 422 Unprocessable Content`.
3. **Uncompressed Size Quota**:
   - The sum of uncompressed member sizes in the ZIP directory table is computed. Archives exceeding `250MB` uncompressed are rejected with `HTTP 422 Unprocessable Content`.
4. **Compression Ratio Defense**:
   - If the ratio of `total_uncompressed_bytes / total_compressed_bytes` exceeds `100.0`, the archive is flagged as a decompression bomb and rejected.
5. **Nested Archive Rejection**:
   - Archives containing embedded archive files (`.zip`, `.tar`, `.gz`, `.bz2`, `.xz`, `.7z`) are rejected to avoid multi-stage recursive unpacking attacks.

---

## 3. Filesystem Sandboxing & Traversal Prevention

Extracting and serving untrusted user files creates risks of directory traversal (`../../`) and symlink escapes:

### 3.1 Path Sanitization
- Prior to extraction, every archive member path is normalized.
- Any path containing parent directory markers (`..`), leading drive letters (`C:`), or root indicators (`/`) is rejected.

### 3.2 Symlink Neutralization
- Archive members that are symbolic links or hardlinks are detected and rejected.
- During source code retrieval, resolved paths are checked with `os.path.realpath()`. The target must strictly reside within the canonical snapshot root directory:
  ```python
  def _resolve_safe_path(base_dir: Path, relative_path: str) -> Path:
      target = (base_dir / relative_path).resolve()
      if not target.is_relative_to(base_dir.resolve()):
          raise PathTraversalError("Path escapes repository snapshot sandbox.")
      return target
  ```

### 3.3 Atomic Staging & Ingestion Isolation
- Archives are extracted into temporary isolated staging directories:
  `storage/repositories/{owner_id}/.staging_{token}/`
- If validation or parsing fails, the entire staging directory is purged.
- Validated uploads are promoted into immutable versioned directories:
  `storage/repositories/{owner_id}/{repo_id}/v{version}/`
- Active snapshots are read-only; new uploads create subsequent versions (`v2`, `v3`).

---

## 4. Graph Isolation in Neo4j

- All nodes (`Module`, `Class`, `Function`, `Route`) are prefixed with the unique `repository_id`.
- Parameterized Cypher queries strictly bind every read, write, and delete operation to the authorized `$repository_id`:
  ```cypher
  MATCH (n {repository_id: $repository_id})
  DETACH DELETE n
  ```
- This guarantees that no graph traversal can leak symbols or dependencies across different user repositories.
