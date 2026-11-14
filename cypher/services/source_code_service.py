"""Source Code Service — persistent snapshot storage and exact source code retrieval.

Responsibilities:
1. Persist immutable repository snapshots onto disk under a structured storage directory.
2. Retrieve complete file contents with encoding detection and path traversal prevention.
3. Retrieve precise line ranges with exact whitespace and comments preserved.
4. Retrieve function and class definitions using AST metadata / knowledge graph line ranges.
"""

from __future__ import annotations

import ast
import logging
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import Any
import uuid

from cypher.config import get_settings
from cypher.graph.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SourceCodeError(Exception):
    """Base exception for source code storage and retrieval errors."""


class PathTraversalError(SourceCodeError):
    """Raised when a file path attempts to escape the repository directory."""


class FileTooLargeError(SourceCodeError):
    """Raised when a requested file exceeds the configured maximum byte limit."""


class RepositoryNotFoundError(SourceCodeError):
    """Raised when repository snapshot directory is not found on disk."""


class SourceFileNotFoundError(SourceCodeError):
    """Raised when a requested file does not exist in the snapshot."""


class InvalidLineRangeError(SourceCodeError):
    """Raised when line range parameters are invalid (e.g. start_line < 1 or start > end)."""


class SymbolNotFoundError(SourceCodeError):
    """Raised when a requested function or class symbol cannot be found in the repository."""


# ---------------------------------------------------------------------------
# Path and Encoding Helpers
# ---------------------------------------------------------------------------

def _resolve_safe_path(snapshot_dir: Path, relative_path: str) -> Path:
    """Validate and resolve a relative file path safely within the snapshot directory.

    Guarantees no directory traversal (e.g. using '../../', absolute paths, or symlink escapes).
    """
    snapshot_root = snapshot_dir.resolve()
    if not snapshot_root.exists() or not snapshot_root.is_dir():
        raise RepositoryNotFoundError(
            f"Repository snapshot directory does not exist: {snapshot_dir}"
        )

    # Clean path and prevent directory traversal
    clean_parts = PurePosixPath(relative_path.replace("\\", "/")).parts
    if any(part == ".." or part.startswith("/") for part in clean_parts):
        raise PathTraversalError(f"Path traversal detected in path: '{relative_path}'")

    target_path = (snapshot_root / Path(*clean_parts)).resolve()

    if not target_path.is_relative_to(snapshot_root):
        raise PathTraversalError(f"Target path escapes snapshot root: '{relative_path}'")

    # In case the file itself is a symlink, ensure its resolved target also stays inside snapshot_root
    try:
        raw_target = snapshot_root / Path(*clean_parts)
        if raw_target.is_symlink() and not raw_target.resolve().is_relative_to(snapshot_root):
            raise PathTraversalError(f"Symlink target escapes snapshot root: '{relative_path}'")
    except OSError:
        pass

    if not target_path.exists() or not target_path.is_file():
        raise SourceFileNotFoundError(f"File '{relative_path}' not found in repository.")

    return target_path


def _read_file_text(path: Path) -> tuple[str, str]:
    """Read file content with robust encoding detection and fallback.

    Returns:
        (text_content, codec_name)
    """
    raw_bytes = path.read_bytes()

    # Try utf-8 first
    try:
        return raw_bytes.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    # Try utf-8-sig (with BOM)
    try:
        return raw_bytes.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        pass

    # Try latin-1 (lossless byte mapping)
    try:
        return raw_bytes.decode("latin-1"), "latin-1"
    except Exception:
        # Final fallback with replacement characters
        return raw_bytes.decode("utf-8", errors="replace"), "utf-8-replace"


def _find_symbol_in_tree(
    tree: ast.AST,
    module_dot_path: str,
    target_qualified_name: str,
    rel_path: str,
) -> tuple[str, int, int, str, str] | None:
    """Recursively search an AST with lexical scope stack for target_qualified_name."""
    scope_stack: list[str] = []

    def _walk(node: ast.AST) -> tuple[str, int, int, str, str] | None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                child_name = child.name
                scope_stack.append(child_name)

                scoped_name = ".".join(scope_stack)
                full_mod_scoped_name = f"{module_dot_path}.{scoped_name}" if module_dot_path else scoped_name

                # Check if matches target
                if (
                    target_qualified_name == full_mod_scoped_name
                    or target_qualified_name == scoped_name
                    or (len(scope_stack) == 1 and target_qualified_name == child_name)
                ):
                    end_ln = getattr(child, "end_lineno", child.lineno)
                    kind = (
                        "class"
                        if isinstance(child, ast.ClassDef)
                        else ("async_function" if isinstance(child, ast.AsyncFunctionDef) else "function")
                    )
                    return rel_path, child.lineno, end_ln, kind, child_name

                # Recurse into child
                res = _walk(child)
                scope_stack.pop()
                if res is not None:
                    return res
        return None

    return _walk(tree)


# ---------------------------------------------------------------------------
# SourceCodeService
# ---------------------------------------------------------------------------

class SourceCodeService:
    """Manages physical source code files on disk and retrieves code segments."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self.storage_dir = (
            Path(storage_dir) if storage_dir else Path(get_settings().storage_dir)
        )

    def get_snapshot_path(
        self,
        owner_id: int | str,
        repository_id: str,
        version: int | None = None,
    ) -> Path:
        """Return the canonical directory for a repository's persistent snapshot.

        If version is specified, returns the specific version directory snapshots/v{version}.
        Otherwise returns the current active snapshot directory.
        """
        repo_base = (self.storage_dir / str(owner_id) / str(repository_id)).resolve()
        if version is not None:
            return repo_base / "snapshots" / f"v{version}"
        current_dir = repo_base / "current"
        if current_dir.exists():
            return current_dir
        # Backwards-compatible check: if legacy directory exists directly at repo_base
        if repo_base.exists() and not (repo_base / "snapshots").exists():
            return repo_base
        return current_dir

    def stage_snapshot(
        self,
        source_dir: Path,
        owner_id: int | str,
        repository_id: str,
    ) -> tuple[Path, str]:
        """Copy extracted source files to an isolated staging directory.

        Returns:
            (staging_path, staging_token)
        """
        repo_base = (self.storage_dir / str(owner_id) / str(repository_id)).resolve()
        token = uuid.uuid4().hex[:12]
        staging_dir = repo_base / f".staging_{token}"
        staging_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, staging_dir, dirs_exist_ok=True)
        return staging_dir, token

    def promote_staged_snapshot(
        self,
        owner_id: int | str,
        repository_id: str,
        staging_token: str,
        version: int,
    ) -> Path:
        """Promote a staged snapshot into the permanent versioned snapshot store.

        Safe on Windows (avoids WinError 5 / locked replace conflicts).
        Returns the canonical Path of the versioned snapshot.
        """
        repo_base = (self.storage_dir / str(owner_id) / str(repository_id)).resolve()
        staging_dir = repo_base / f".staging_{staging_token}"
        if not staging_dir.exists():
            raise SourceCodeError(f"Staged snapshot not found: {staging_dir}")

        snapshots_dir = repo_base / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        version_dir = snapshots_dir / f"v{version}"

        if version_dir.exists():
            retiring_dir = repo_base / f".retiring_{version}_{uuid.uuid4().hex[:8]}"
            try:
                version_dir.rename(retiring_dir)
                shutil.rmtree(retiring_dir, ignore_errors=True)
            except OSError:
                shutil.rmtree(version_dir, ignore_errors=True)

        shutil.copytree(staging_dir, version_dir, dirs_exist_ok=True)

        # Update current pointer snapshot
        current_dir = repo_base / "current"
        if current_dir.exists():
            shutil.rmtree(current_dir, ignore_errors=True)
        shutil.copytree(version_dir, current_dir, dirs_exist_ok=True)

        # Clean staging directory
        shutil.rmtree(staging_dir, ignore_errors=True)

        logger.info(
            "Promoted staged snapshot to version %d for repo '%s' at: %s",
            version,
            repository_id,
            version_dir,
        )
        return version_dir

    def cleanup_staged_snapshot(
        self,
        owner_id: int | str,
        repository_id: str,
        staging_token: str,
    ) -> None:
        """Clean up an unpromoted staging directory upon analysis or ingestion failure."""
        repo_base = (self.storage_dir / str(owner_id) / str(repository_id)).resolve()
        staging_dir = repo_base / f".staging_{staging_token}"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
            logger.info("Cleaned unpromoted staging directory: %s", staging_dir)

    def store_snapshot(
        self,
        source_dir: Path,
        owner_id: int | str,
        repository_id: str,
        version: int | None = None,
    ) -> Path:
        """Copy extracted repository files into persistent, immutable versioned storage.

        Preserves past versions under snapshots/v{version}/ and points 'current' to the latest.
        Returns the absolute Path of the stored snapshot.
        """
        staging_dir, token = self.stage_snapshot(source_dir, owner_id, repository_id)
        if version is None:
            repo_base = (self.storage_dir / str(owner_id) / str(repository_id)).resolve()
            snapshots_dir = repo_base / "snapshots"
            existing_versions = []
            if snapshots_dir.exists():
                for d in snapshots_dir.iterdir():
                    if d.is_dir() and d.name.startswith("v") and d.name[1:].isdigit():
                        existing_versions.append(int(d.name[1:]))
            version = max(existing_versions) + 1 if existing_versions else 1

        return self.promote_staged_snapshot(owner_id, repository_id, token, version)

    def get_file_content(
        self,
        snapshot_dir: Path,
        relative_path: str,
    ) -> dict[str, Any]:
        """Retrieve full text content of a file in the snapshot.

        Returns:
            dict containing: file_path, content, total_lines, size_bytes, encoding.
        """
        target_file = _resolve_safe_path(snapshot_dir, relative_path)
        settings = get_settings()
        file_size = target_file.stat().st_size
        if file_size > settings.max_source_file_bytes:
            raise FileTooLargeError(
                f"File '{relative_path}' size ({file_size} bytes) exceeds maximum "
                f"allowed limit ({settings.max_source_file_bytes} bytes)."
            )

        content, encoding = _read_file_text(target_file)
        lines = content.splitlines(keepends=True)

        # Normalize relative path using forward slashes
        clean_rel = str(target_file.relative_to(snapshot_dir.resolve())).replace("\\", "/")

        return {
            "file_path": clean_rel,
            "content": content,
            "total_lines": len(lines),
            "size_bytes": file_size,
            "encoding": encoding,
        }

    def get_line_range(
        self,
        snapshot_dir: Path,
        relative_path: str,
        start_line: int,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        """Extract a specific range of lines (1-indexed, inclusive) from a source file.

        Preserves exact indentation, comments, and whitespace.
        """
        if start_line < 1:
            raise InvalidLineRangeError("start_line must be greater than or equal to 1.")

        if end_line is not None and end_line < start_line:
            raise InvalidLineRangeError(
                f"end_line ({end_line}) cannot be less than start_line ({start_line})."
            )

        target_file = _resolve_safe_path(snapshot_dir, relative_path)
        content, encoding = _read_file_text(target_file)
        all_lines = content.splitlines(keepends=True)
        total_lines = len(all_lines)

        if total_lines == 0:
            return {
                "file_path": relative_path,
                "start_line": 1,
                "end_line": 0,
                "total_lines": 0,
                "content": "",
                "lines": [],
            }

        if start_line > total_lines:
            raise InvalidLineRangeError(
                f"start_line ({start_line}) exceeds total lines in file ({total_lines})."
            )

        actual_end = min(end_line, total_lines) if end_line is not None else total_lines
        range_count = actual_end - start_line + 1
        settings = get_settings()
        if range_count > settings.max_range_lines:
            raise InvalidLineRangeError(
                f"Requested range of {range_count} lines exceeds the maximum limit "
                f"of {settings.max_range_lines} lines."
            )

        # 1-indexed to 0-indexed slicing
        extracted_slice = all_lines[start_line - 1 : actual_end]
        extracted_content = "".join(extracted_slice)

        clean_rel = str(target_file.relative_to(snapshot_dir.resolve())).replace("\\", "/")

        return {
            "file_path": clean_rel,
            "start_line": start_line,
            "end_line": actual_end,
            "total_lines": total_lines,
            "content": extracted_content,
            "lines": [line.rstrip("\r\n") for line in extracted_slice],
        }

    def get_symbol_source(
        self,
        snapshot_dir: Path,
        qualified_name: str,
        *,
        neo4j_client: Neo4jClient | None = None,
        repository_id: str | None = None,
    ) -> dict[str, Any]:
        """Find a function or class definition by qualified name and extract its exact source code.

        Lookup steps:
        1. If Neo4j is available, query the node's file_path, line, and end_line.
        2. Fallback: Parse Python AST of snapshot files to locate the symbol definition.
        3. Extract the exact line slice from the source file.
        """
        file_path: str | None = None
        start_line: int | None = None
        end_line: int | None = None
        kind: str = "function"
        symbol_name: str = qualified_name.split(".")[-1]

        # 1. Try Neo4j node lookup if available
        if neo4j_client is not None and repository_id is not None:
            try:
                cypher = """
                MATCH (e:Entity {repository_id: $repo_id, qualified_name: $name})
                WHERE e:Function OR e:Class
                RETURN e.file_path AS file_path,
                       e.line AS line,
                       e.end_line AS end_line,
                       e.name AS name,
                       [lbl IN labels(e) WHERE lbl <> 'Entity'][0] AS kind
                LIMIT 1
                """
                records = neo4j_client.execute_query(
                    cypher, {"repo_id": repository_id, "name": qualified_name}
                )
                if isinstance(records, list) and len(records) > 0 and isinstance(records[0], dict):
                    rec = records[0]
                    fp = rec.get("file_path")
                    ln = rec.get("line")
                    end_ln = rec.get("end_line") or ln
                    if isinstance(fp, str) and isinstance(ln, int):
                        file_path = fp
                        start_line = ln
                        end_line = end_ln if isinstance(end_ln, int) else ln
                        kind = rec.get("kind") or "function"
                        symbol_name = rec.get("name") or symbol_name
            except Exception as exc:
                logger.warning("Neo4j symbol lookup error: %s", exc)

        # 2. AST Fallback if not found via Neo4j
        if not file_path or not start_line:
            found = self._find_symbol_via_ast(snapshot_dir, qualified_name)
            if not found:
                raise SymbolNotFoundError(
                    f"Symbol '{qualified_name}' was not found in repository."
                )
            file_path, start_line, end_line, kind, symbol_name = found

        range_result = self.get_line_range(
            snapshot_dir, file_path, start_line, end_line
        )

        return {
            "qualified_name": qualified_name,
            "name": symbol_name,
            "kind": kind,
            "file_path": range_result["file_path"],
            "start_line": range_result["start_line"],
            "end_line": range_result["end_line"],
            "total_file_lines": range_result["total_lines"],
            "source_code": range_result["content"],
        }

    def _find_symbol_via_ast(
        self,
        snapshot_dir: Path,
        qualified_name: str,
    ) -> tuple[str, int, int, str, str] | None:
        """Search Python files in snapshot_dir for a function, class, or method definition.

        Uses lexical scope tracking to accurately resolve qualified names like:
        - top-level function: 'hello' or 'users.views.hello'
        - class: 'User' or 'users.models.User'
        - method: 'User.save' or 'users.models.User.save'
        - nested function/class: 'outer.inner' or 'ClassA.NestedClass.method'
        """
        for py_file in snapshot_dir.rglob("*.py"):
            try:
                code_text, _ = _read_file_text(py_file)
                tree = ast.parse(code_text, filename=str(py_file))
            except Exception:
                continue

            rel_path = str(py_file.relative_to(snapshot_dir.resolve())).replace("\\", "/")

            # Construct module dotted path: e.g. "users/views.py" -> "users.views"
            mod_parts = list(py_file.relative_to(snapshot_dir.resolve()).parts)
            if mod_parts[-1].endswith(".py"):
                mod_parts[-1] = mod_parts[-1][:-3]
            if mod_parts[-1] == "__init__":
                mod_parts.pop()
            module_dot_path = ".".join(mod_parts)

            # Traverse AST maintaining scope stack
            found = _find_symbol_in_tree(tree, module_dot_path, qualified_name, rel_path)
            if found:
                return found

        return None
