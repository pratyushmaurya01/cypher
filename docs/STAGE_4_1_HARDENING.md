# Stage 4.1 Architecture & Verification: Source Retrieval Hardening & Isolation

## 1. Executive Summary
In Stage 4.1, the source code retrieval and storage layer of **Cypher** was hardened to guarantee data integrity, reliable repository identification, version history preservation, and robust cross-user isolation.

All changes were verified against the full regression suite (**120/120 passing tests**).

---

## 2. Core Architectural Upgrades

### A. Stable Repository Identity Strategy
- **Issue:** Previously, `repository_id` was derived via `_stable_id("repo", repo_root)` where `repo_root` resided within a temporary directory (e.g. `tempfile.TemporaryDirectory`). Every re-upload generated a new random repository ID.
- **Solution:** Repository identity is now deterministically calculated based on owner identity and repository name:
  $$\text{repo\_id} = \text{"repo\_"} + \text{SHA256}(\text{owner\_id} : \text{repo\_name})[:16]$$
- **Benefits:**
  - Repeated uploads by the same user retain the same stable `repository_id`.
  - Different users uploading projects with identical directory names receive completely isolated repository IDs and storage directories.

### B. Immutable Versioned Snapshots
- **Issue:** `SourceCodeService.store_snapshot()` used `shutil.rmtree()` on existing repository directories, destroying past version history.
- **Solution:**
  - Replaced destructive overwriting with immutable version subdirectories:
    `storage/repositories/{owner_id}/{repo_id}/snapshots/v{version}/`
  - Added `current_version` tracking in PostgreSQL (`RepositoryMetadata`).
  - Added an active alias/directory `current/` pointing to the latest snapshot.
  - Prior versions (`v1`, `v2`, ...) remain intact and accessible on disk.

### C. Path Traversal & Symlink Protection
- **Issue:** Security check relied on `str(target_path).startswith(str(snapshot_root))`, which was vulnerable to edge-case prefix collisions and unverified symlink targets.
- **Solution:**
  - Enforced `Path.resolve().is_relative_to(snapshot_root.resolve())`.
  - Added explicit symlink target resolution: if a file in the snapshot is a symlink, its resolved destination must also remain inside `snapshot_root`.
  - Path traversal attempts, relative escapes (`../../`), and symlink escapes immediately raise `PathTraversalError`.

### D. Lexical Scope AST Symbol Disambiguation
- **Issue:** AST fallback lookup matched symbols using simple suffix equality `node.name == parts[-1]`. If multiple functions/classes shared the same name across nested scopes or files (e.g., `compute()`, `Outer.Inner.compute()`, `models.User`), incorrect symbols could be returned.
- **Solution:**
  - Implemented `_find_symbol_in_tree()` using an AST visitor with lexical scope tracking.
  - Matches symbols against both file-scoped (`OuterClass.InnerClass.method`) and fully qualified (`module.OuterClass.InnerClass.method`) identifiers.

### E. Pre-Ingestion Ownership Validation
- **Issue:** Previously, `run_analysis()` wiped and rebuilt Neo4j nodes before verifying ownership in PostgreSQL. A colliding upload could wipe another user's graph data before raising HTTP 403.
- **Solution:** Ownership is now verified in PostgreSQL **prior** to any AST analysis, disk write, or Neo4j ingestion.

### F. Production Authentication Enforcement & Rate Safeguards
- Anonymous fallback access (`dev-anonymous@cypher.local`) is strictly blocked in production mode (`settings.effective_allow_anonymous_dev`).
- Added configurable safeguards:
  - `max_source_file_bytes`: 2 MB (Files exceeding this return HTTP 413).
  - `max_range_lines`: 1,000 lines (Requests exceeding this return HTTP 400).

---

## 3. Test Coverage & Verification Results

The entire test suite passed successfully:

```
====================== 120 passed, 4 warnings in 35.32s =======================
```

### New Tests (`tests/test_stage4_hardening.py`):
1. `test_reupload_preserves_repository_id_and_increments_version`: Verifies stable `repository_id` and version increment (`v1 -> v2`) with disk persistence.
2. `test_different_users_uploading_identical_repository_remain_isolated`: Verifies that distinct owners get different repo IDs and paths for identical ZIP contents.
3. `test_path_traversal_and_symlink_checks`: Verifies rejection of traversal paths and symlink escapes.
4. `test_ast_lexical_scope_lookup_resolves_nested_symbols_and_avoids_collision`: Verifies correct symbol retrieval across top-level functions, nested classes, and instance methods.
5. `test_cross_user_source_retrieval_forbidden`: Verifies 403 Forbidden for cross-user file, range, and symbol retrieval.
6. `test_file_size_and_range_retrieval_limits`: Verifies rejection of oversized files and line ranges.
7. `test_production_authentication_enforcement`: Verifies 401 Unauthorized for unauthenticated requests when `app_env == "production"`.
