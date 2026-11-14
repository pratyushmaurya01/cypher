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

    Guarantees no directory traversal (e.g. using '../../' or absolute paths).
    """
    if not snapshot_dir.exists() or not snapshot_dir.is_dir():
        raise RepositoryNotFoundError(
            f"Repository snapshot directory does not exist: {snapshot_dir}"
        )

    # Clean path and prevent directory traversal
    clean_parts = PurePosixPath(relative_path.replace("\\", "/")).parts
    if any(part == ".." or part.startswith("/") for part in clean_parts):
        raise PathTraversalError(f"Path traversal detected in path: '{relative_path}'")

    target_path = (snapshot_dir / Path(*clean_parts)).resolve()
    snapshot_root = snapshot_dir.resolve()

    if not str(target_path).startswith(str(snapshot_root)):
        raise PathTraversalError(f"Target path escapes snapshot root: '{relative_path}'")

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


# ---------------------------------------------------------------------------
# SourceCodeService
# ---------------------------------------------------------------------------

class SourceCodeService:
    """Manages physical source code files on disk and retrieves code segments."""

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self.storage_dir = (
            Path(storage_dir) if storage_dir else Path(get_settings().storage_dir)
        )

    def get_snapshot_path(self, owner_id: int | str, repository_id: str) -> Path:
        """Return the canonical directory for a repository's persistent snapshot."""
        return (self.storage_dir / str(owner_id) / str(repository_id)).resolve()

    def store_snapshot(
        self,
        source_dir: Path,
        owner_id: int | str,
        repository_id: str,
    ) -> Path:
        """Copy extracted repository files into persistent, immutable storage.

        Overwrites any previous snapshot for this repository.
        Returns the absolute Path of the stored snapshot.
        """
        dest_dir = self.get_snapshot_path(owner_id, repository_id)

        # Clear existing snapshot if re-analyzing
        if dest_dir.exists():
            shutil.rmtree(dest_dir)

        dest_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_dir, dest_dir)
        logger.info(
            "Stored persistent repository snapshot for repo '%s' at: %s",
            repository_id,
            dest_dir,
        )
        return dest_dir

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
        content, encoding = _read_file_text(target_file)
        lines = content.splitlines(keepends=True)

        # Normalize relative path using forward slashes
        clean_rel = str(target_file.relative_to(snapshot_dir.resolve())).replace("\\", "/")

        return {
            "file_path": clean_rel,
            "content": content,
            "total_lines": len(lines),
            "size_bytes": target_file.stat().st_size,
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
        """Search Python files in snapshot_dir for a function or class definition."""
        parts = qualified_name.split(".")

        for py_file in snapshot_dir.rglob("*.py"):
            try:
                code_text, _ = _read_file_text(py_file)
                tree = ast.parse(code_text, filename=str(py_file))
            except Exception:
                continue

            rel_path = str(py_file.relative_to(snapshot_dir.resolve())).replace("\\", "/")

            # Traverse top-level definitions
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    # Match by node name if qualified matches either full or end segment
                    if node.name == parts[-1]:
                        end_ln = getattr(node, "end_lineno", node.lineno)
                        kind = (
                            "class"
                            if isinstance(node, ast.ClassDef)
                            else ("async_function" if isinstance(node, ast.AsyncFunctionDef) else "function")
                        )
                        return rel_path, node.lineno, end_ln, kind, node.name
        return None
