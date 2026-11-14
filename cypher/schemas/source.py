"""Pydantic schemas for source code retrieval endpoints."""

from __future__ import annotations

from typing import List
from pydantic import BaseModel, Field


class FileContentResponse(BaseModel):
    """Full content of a source file within a repository."""

    repository_id: str
    file_path: str
    content: str
    total_lines: int
    size_bytes: int
    encoding: str


class CodeRangeResponse(BaseModel):
    """Specific line range from a source file."""

    repository_id: str
    file_path: str
    start_line: int
    end_line: int
    total_lines: int
    content: str
    lines: List[str] = Field(default_factory=list)


class SymbolSourceResponse(BaseModel):
    """Exact source code definition for an analyzed function or class symbol."""

    repository_id: str
    qualified_name: str
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    total_file_lines: int
    source_code: str
