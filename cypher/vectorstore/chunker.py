"""AST-aware code chunker for semantic indexing.

Walks every Python source file in a repository snapshot and produces
meaningful, self-contained chunks with full metadata.  Chunks are
designed to map cleanly to ChromaDB documents.

Chunk strategy (in priority order):
  1. Each class definition (with its docstring and decorators).
  2. Each function / method / async function definition (with decorators).
  3. Module-level code (import blocks, constants, top-level assignments) as
     a single fallback chunk per file.

Excluded from indexing:
  - __pycache__, .venv, venv, node_modules, migrations (generated).
  - Files that cannot be decoded as text.
  - Files with zero meaningful content after stripping.
"""

from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

# Directories that should never be indexed
_SKIP_DIRS: frozenset[str] = frozenset({
    "__pycache__", ".venv", "venv", ".git", "node_modules",
    "dist", "build", ".tox", ".eggs",
})

# Skip generated migration files from Django / Alembic
_SKIP_PATH_PATTERNS: tuple[str, ...] = (
    "migrations/0",   # Django migration files
    "alembic/versions/",
)

# Maximum source lines per chunk — very long definitions get a header+tail slice
_MAX_CHUNK_LINES = 300


@dataclass
class CodeChunk:
    """A single indexable unit of source code."""

    # Identity
    repository_id: str
    chunk_id: str = ""             # sha256 of (repository_id + file_path + symbol)
    file_path: str = ""            # relative to snapshot root
    symbol_name: str = ""          # short name (e.g. "LoginView")
    qualified_name: str = ""       # fully qualified (e.g. "users.views.LoginView")
    symbol_type: str = "function"  # "class" | "function" | "method" | "module"

    # Location
    start_line: int = 0
    end_line: int = 0

    # Content
    source_code: str = ""          # exact source text (may be truncated for huge blocks)
    docstring: str = ""
    decorator_names: list[str] = field(default_factory=list)
    signature: str = ""            # first line of def/class

    # Embedding input — combines signature + docstring + source
    embed_text: str = ""

    # Content hash — used for idempotent re-indexing
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.chunk_id:
            raw_id = f"{self.repository_id}:{self.file_path}:{self.qualified_name or self.symbol_name}:{self.start_line}"
            self.chunk_id = hashlib.sha256(raw_id.encode()).hexdigest()[:24]
        if not self.content_hash:
            raw = f"{self.repository_id}:{self.file_path}:{self.symbol_name}:{self.source_code}"
            self.content_hash = hashlib.sha256(raw.encode()).hexdigest()
        if not self.embed_text:
            parts = []
            if self.decorator_names:
                parts.append(" ".join(self.decorator_names))
            if self.signature:
                parts.append(self.signature)
            if self.docstring:
                parts.append(self.docstring)
            parts.append(self.source_code[:3000])   # cap embed input
            self.embed_text = "\n".join(parts).strip()

    def to_chroma_document(self) -> dict:
        """Serialize chunk for ChromaDB upsert."""
        return {
            "id": self.chunk_id,
            "document": self.embed_text,
            "metadata": {
                "repository_id": self.repository_id,
                "file_path": self.file_path,
                "symbol_name": self.symbol_name,
                "qualified_name": self.qualified_name,
                "symbol_type": self.symbol_type,
                "start_line": self.start_line,
                "end_line": self.end_line,
                "docstring": self.docstring[:500],
                "signature": self.signature[:300],
                "content_hash": self.content_hash,
                "embedding_model": "",   # filled in by chroma_store before upsert
            },
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chunk_repository(
    snapshot_dir: Path,
    repository_id: str,
    module_prefix: str = "",
) -> list[CodeChunk]:
    """Walk *snapshot_dir* and produce CodeChunk objects for every Python file.

    Args:
        snapshot_dir: Absolute path to the repository snapshot directory.
        repository_id: Stable repository identifier (e.g. ``repo_01429290b8d99cd7``).
        module_prefix: Optional dotted module prefix prepended to file-based names.

    Returns:
        List of CodeChunk objects ordered by file, then start_line.
    """
    chunks: list[CodeChunk] = []
    snapshot_dir = snapshot_dir.resolve()

    for py_file in _walk_python_files(snapshot_dir):
        rel_path = py_file.relative_to(snapshot_dir)
        rel_str = str(rel_path).replace("\\", "/")

        if _should_skip_path(rel_str):
            continue

        source = _read_source(py_file)
        if source is None:
            continue

        try:
            tree = ast.parse(source, filename=rel_str)
        except SyntaxError as exc:
            logger.debug("Skipping %s — syntax error: %s", rel_str, exc)
            continue

        file_module = _file_to_module(rel_str, module_prefix)
        file_chunks = list(_extract_chunks(source, tree, repository_id, rel_str, file_module))

        if not file_chunks:
            # Fallback: index entire file as one module chunk
            fallback = _make_module_chunk(source, repository_id, rel_str, file_module)
            if fallback:
                file_chunks = [fallback]

        chunks.extend(file_chunks)

    logger.info("Chunked %d code chunks from %s", len(chunks), snapshot_dir)
    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _walk_python_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*.py"):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def _should_skip_path(rel_str: str) -> bool:
    return any(pattern in rel_str for pattern in _SKIP_PATH_PATTERNS)


def _read_source(path: Path) -> str | None:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except (UnicodeDecodeError, OSError):
            continue
    logger.debug("Cannot read %s — skipping", path)
    return None


def _file_to_module(rel_path: str, prefix: str) -> str:
    """Convert ``users/views.py`` → ``users.views``."""
    module = rel_path.replace("/", ".").removesuffix(".py").removesuffix(".__init__")
    if prefix:
        module = f"{prefix}.{module}"
    return module


def _get_source_segment(source: str, node: ast.AST) -> tuple[str, int, int]:
    """Extract exact source lines for an AST node."""
    lines = source.splitlines(keepends=True)
    start = node.lineno - 1          # ast lineno is 1-indexed
    end = getattr(node, "end_lineno", node.lineno)
    segment_lines = lines[start:end]
    # Truncate huge blocks
    if len(segment_lines) > _MAX_CHUNK_LINES:
        segment_lines = segment_lines[:_MAX_CHUNK_LINES]
        segment_lines.append(f"    # ... [{len(lines[start:end]) - _MAX_CHUNK_LINES} lines truncated]\n")
    return "".join(segment_lines), node.lineno, end


def _get_docstring(node: ast.AST) -> str:
    return ast.get_docstring(node) or ""


def _get_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> list[str]:
    result = []
    for dec in node.decorator_list:
        try:
            result.append(f"@{ast.unparse(dec)}")
        except Exception:
            result.append("@<decorator>")
    return result


def _make_chunk_id(repository_id: str, file_path: str, qualified_name: str, start_line: int) -> str:
    raw = f"{repository_id}:{file_path}:{qualified_name}:{start_line}"
    return "chunk_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _extract_chunks(
    source: str,
    tree: ast.Module,
    repository_id: str,
    file_path: str,
    file_module: str,
    _scope: str = "",
) -> Iterator[CodeChunk]:
    """Recursively extract chunks from classes and functions."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef,)):
            yield from _chunk_class(source, node, repository_id, file_path, file_module, _scope)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _chunk_function(source, node, repository_id, file_path, file_module, _scope)


def _chunk_class(
    source: str,
    node: ast.ClassDef,
    repository_id: str,
    file_path: str,
    file_module: str,
    scope: str,
) -> Iterator[CodeChunk]:
    qual = f"{file_module}.{scope + '.' if scope else ''}{node.name}"
    code, start, end = _get_source_segment(source, node)
    decorators = _get_decorators(node)
    docstring = _get_docstring(node)
    # First line of class def as signature
    sig_line = code.split("\n")[0].strip() if code else f"class {node.name}:"
    bases = [ast.unparse(b) for b in node.bases]
    if bases:
        sig_line = f"class {node.name}({', '.join(bases)}):"

    yield CodeChunk(
        repository_id=repository_id,
        chunk_id=_make_chunk_id(repository_id, file_path, qual, start),
        file_path=file_path,
        symbol_name=node.name,
        qualified_name=qual,
        symbol_type="class",
        start_line=start,
        end_line=end,
        source_code=code,
        docstring=docstring,
        decorator_names=decorators,
        signature=sig_line,
    )

    # Recurse into class body for methods
    new_scope = f"{scope}.{node.name}" if scope else node.name
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _chunk_function(
                source, child, repository_id, file_path, file_module, new_scope
            )


def _chunk_function(
    source: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    repository_id: str,
    file_path: str,
    file_module: str,
    scope: str,
) -> Iterator[CodeChunk]:
    qual = f"{file_module}.{scope + '.' if scope else ''}{node.name}"
    sym_type = "method" if "." in scope else "function"
    code, start, end = _get_source_segment(source, node)
    decorators = _get_decorators(node)
    docstring = _get_docstring(node)

    try:
        args = ast.unparse(node.args)
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        signature = f"{prefix} {node.name}({args}):"
    except Exception:
        signature = f"def {node.name}(...):"

    yield CodeChunk(
        repository_id=repository_id,
        chunk_id=_make_chunk_id(repository_id, file_path, qual, start),
        file_path=file_path,
        symbol_name=node.name,
        qualified_name=qual,
        symbol_type=sym_type,
        start_line=start,
        end_line=end,
        source_code=code,
        docstring=docstring,
        decorator_names=decorators,
        signature=signature,
    )

    # Recurse into nested functions
    new_scope = f"{scope}.{node.name}" if scope else node.name
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield from _chunk_function(
                source, child, repository_id, file_path, file_module, new_scope
            )


def _make_module_chunk(
    source: str,
    repository_id: str,
    file_path: str,
    file_module: str,
) -> CodeChunk | None:
    """Fallback: treat the whole file as a single module-level chunk."""
    stripped = source.strip()
    if not stripped:
        return None
    lines = source.splitlines()
    return CodeChunk(
        repository_id=repository_id,
        chunk_id=_make_chunk_id(repository_id, file_path, file_module, 1),
        file_path=file_path,
        symbol_name=file_module.split(".")[-1],
        qualified_name=file_module,
        symbol_type="module",
        start_line=1,
        end_line=len(lines),
        source_code=source[:5000],   # cap very large files
        signature=f"# module: {file_module}",
    )
