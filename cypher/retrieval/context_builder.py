"""Context builder — fetches exact source code and formats evidence for the LLM.

For each FusedEvidence item the builder:
  1. Validates the file_path and line numbers against the snapshot on disk.
  2. Fetches exact source code using SourceCodeService.get_line_range().
  3. Formats each block as a labeled markdown fenced code block.
  4. Budgets total context to stay within ``rag_context_max_tokens`` chars.
  5. Returns the formatted context string AND a list of validated SourceCitation objects.
"""

from __future__ import annotations

import logging
from pathlib import Path

from cypher.schemas.rag import FusedEvidence, SourceCitation
from cypher.services.source_code_service import (
    InvalidLineRangeError,
    RepositoryNotFoundError,
    SourceCodeService,
    SourceFileNotFoundError,
)

logger = logging.getLogger(__name__)


def build_context(
    evidence_list: list[FusedEvidence],
    snapshot_dir: Path,
    repository_id: str,
    max_chars: int = 24_000,
) -> tuple[str, list[SourceCitation]]:
    """Fetch source code for each evidence item and format an LLM-ready context string.

    Args:
        evidence_list:  Ranked FusedEvidence items (best first from RRF).
        snapshot_dir:   Path to the repository snapshot on disk.
        repository_id:  Used for logging only (isolation is enforced upstream).
        max_chars:      Approximate character budget for the total context string.

    Returns:
        (context_string, citations)
        - context_string: Formatted evidence ready to inject into the LLM prompt.
        - citations: Validated SourceCitation objects to include in ChatResponse.
    """
    svc = SourceCodeService()
    blocks: list[str] = []
    citations: list[SourceCitation] = []
    total_chars = 0

    for ev in evidence_list:
        if total_chars >= max_chars:
            logger.debug(
                "Context builder: budget exhausted at %d chars, skipping remaining evidence",
                total_chars,
            )
            break

        # Validate and fetch source
        snippet = _fetch_snippet(svc, snapshot_dir, ev)
        if snippet is None:
            continue

        # Truncate very long snippets to protect budget
        snippet_chars = len(snippet)
        if snippet_chars > 4_000:
            snippet = snippet[:4_000] + "\n# ... (truncated)"
            snippet_chars = len(snippet)

        if total_chars + snippet_chars > max_chars:
            # Include a partial snippet if there's budget left
            remaining = max_chars - total_chars
            if remaining < 200:
                break
            snippet = snippet[:remaining] + "\n# ... (truncated)"
            snippet_chars = len(snippet)

        # Format the block header
        header = (
            f"[FILE: {ev.file_path} | "
            f"SYMBOL: {ev.symbol_name or ev.qualified_name} | "
            f"TYPE: {ev.symbol_type} | "
            f"LINES: {ev.start_line}-{ev.end_line} | "
            f"SOURCE: {ev.source} | "
            f"RRF: {ev.rrf_score:.4f}]"
        )
        code_block = (
            f"{header}\n"
            f"```python\n"
            f"# {ev.file_path} (Lines {ev.start_line}-{ev.end_line})\n"
            f"{snippet.rstrip()}\n"
            f"```"
        )
        blocks.append(code_block)
        total_chars += snippet_chars + len(header) + 20   # rough overhead

        citations.append(
            SourceCitation(
                file_path=ev.file_path,
                symbol_name=ev.symbol_name or ev.qualified_name,
                symbol_type=ev.symbol_type,
                start_line=ev.start_line,
                end_line=ev.end_line,
                snippet=snippet,
                score=ev.rrf_score,
                source=ev.source,
            )
        )

    context_string = "\n\n---\n\n".join(blocks) if blocks else "No code evidence was retrieved."

    logger.debug(
        "Context builder: %d/%d evidence items included, %d chars total (repo=%s)",
        len(citations), len(evidence_list), total_chars, repository_id,
    )
    return context_string, citations


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_snippet(
    svc: SourceCodeService,
    snapshot_dir: Path,
    ev: FusedEvidence,
) -> str | None:
    """Safely fetch source lines for an evidence item. Returns None on any error."""
    if not ev.file_path or ev.start_line <= 0:
        logger.debug(
            "Context builder: skipping evidence with missing file_path or start_line: %s",
            ev.dedup_key,
        )
        return None

    try:
        result = svc.get_line_range(
            snapshot_dir=snapshot_dir,
            relative_path=ev.file_path,
            start_line=ev.start_line,
            end_line=ev.end_line if ev.end_line > 0 else None,
        )
        return result.get("content", "")
    except RepositoryNotFoundError:
        logger.warning(
            "Context builder: snapshot directory not found: %s", snapshot_dir
        )
        return None
    except SourceFileNotFoundError:
        logger.debug(
            "Context builder: file not found in snapshot: %s (skipping)", ev.file_path
        )
        return None
    except InvalidLineRangeError as exc:
        logger.debug(
            "Context builder: invalid line range %s:%d-%d — %s",
            ev.file_path, ev.start_line, ev.end_line, exc,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Context builder: unexpected error fetching %s:%d-%d — %s",
            ev.file_path, ev.start_line, ev.end_line, exc,
        )
        return None
