"""Response schemas for graph retrieval endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepositoryOverview(BaseModel):
    """High-level statistics for a repository graph."""

    repository_id: str
    total_modules: int
    total_classes: int
    total_functions: int
    total_external_dependencies: int
    total_calls: int
    total_routes: int


class RouteItem(BaseModel):
    """A single HTTP route and its handler."""

    source: str = Field(..., description="Qualified name of the URL module.")
    route: str | None = Field(None, description="URL pattern string.")
    http_methods: list[str] = Field(default_factory=list)
    url_name: str | None = None
    handler: str = Field(..., description="Qualified name of the handler function.")
    file: str | None = None


class FunctionDependency(BaseModel):
    """An entity called or instantiated by a function."""

    target: str = Field(..., description="Qualified name of the target entity.")
    kind: str | None = Field(None, description="'Function', 'Class', etc.")
    file: str | None = None
    depth: int = Field(..., description="Number of hops from the source function.")


class FunctionCaller(BaseModel):
    """A function that calls the queried function."""

    caller: str
    file: str | None = None
    depth: int


class ModuleDependencies(BaseModel):
    """Import relationships for a module (both directions)."""

    module_name: str
    imports: list[dict] = Field(default_factory=list)
    imported_by: list[dict] = Field(default_factory=list)


class ClassHierarchy(BaseModel):
    """Superclasses and subclasses for a class."""

    class_name: str
    superclasses: list[str] = Field(default_factory=list)
    subclasses: list[str] = Field(default_factory=list)


class DeadCodeCandidate(BaseModel):
    """A function that appears to be never called (heuristic)."""

    unused_function: str
    file: str | None = None
    line: int | None = None
    note: str = Field(
        default="Heuristic candidate: verified via static analysis, dynamic callers or external hooks may exist.",
        description="Explains that dead code detection is heuristic.",
    )


class EntityItem(BaseModel):
    """A graph entity node (Module, Class, Function, etc.)."""

    id: str
    repository_id: str | None = None
    name: str
    qualified_name: str
    kind: str
    file_path: str | None = None
    line: int | None = None
    end_line: int | None = None


class EntityDetail(BaseModel):
    """Detailed entity attributes and relationships."""

    entity: EntityItem
    incoming_relationships: list[dict] = Field(default_factory=list)
    outgoing_relationships: list[dict] = Field(default_factory=list)


class FileDependencies(BaseModel):
    """Import and call relationships between files."""

    repository_id: str
    file_path: str
    imported_files: list[str] = Field(default_factory=list)
    imported_by_files: list[str] = Field(default_factory=list)
