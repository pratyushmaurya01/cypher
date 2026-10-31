"""Unit tests for Stage 1 static analysis enhancements.

Verifies:
- Instance method call resolution (var.method() -> Class.method)
- SymbolIndex duplicate qualified name candidate handling and ambiguity detection
- Scope-aware import maps and external vs unresolved distinction
- FastAPI include_router argument and prefix extraction
- Flask register_blueprint argument and prefix extraction
- RelationshipBuilder referential integrity validation (zero dangling pointers)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cypher.analyzer.ast_parser import parse_repository
from cypher.analyzer.engine import analyze_repository
from cypher.resolver.fastapi_resolver import FastAPIResolver
from cypher.resolver.flask_resolver import FlaskResolver
from cypher.resolver.import_resolver import ImportResolver
from cypher.resolver.relationship_builder import validate_graph
from cypher.resolver.symbol_index import SymbolIndex


def test_instance_method_call_resolution(tmp_path):
    """Local constructor assignment allows var.method() resolution to Class.method."""
    (tmp_path / "services.py").write_text(
        """
class UserService:
    def get_users(self):
        return []
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "controller.py").write_text(
        """
from services import UserService

def handle_request():
    service = UserService()
    return service.get_users()
""".lstrip(),
        encoding="utf-8",
    )

    result = analyze_repository(tmp_path)
    calls = [r for r in result["relationships"] if r["type"] == "CALLS"]
    instantiates = [r for r in result["relationships"] if r["type"] == "INSTANTIATES"]

    # Verify constructor call
    assert any(
        i["source_qualified"] == "controller.handle_request"
        and i["target_qualified"] == "services.UserService"
        for i in instantiates
    )

    # Verify instance method call
    assert any(
        c["source_qualified"] == "controller.handle_request"
        and c["target_qualified"] == "services.UserService.get_users"
        and c["method"] == "instance_method"
        for c in calls
    )


def test_symbol_index_duplicate_qualified_names(tmp_path):
    """SymbolIndex records all candidates for duplicate definitions without overwriting."""
    (tmp_path / "conditional.py").write_text(
        """
def compute():
    return 1

def compute():
    return 2
""".lstrip(),
        encoding="utf-8",
    )

    parsed = parse_repository(tmp_path)
    index = SymbolIndex(parsed["files"])

    candidates = index.lookup_candidates("conditional.compute")
    assert len(candidates) == 2
    assert index.is_ambiguous("conditional.compute") is True
    # Stable IDs are preserved
    assert candidates[0]["id"] != candidates[1]["id"]


def test_scope_aware_import_resolution(tmp_path):
    """Scoped import map isolates function-level imports from module scope."""
    (tmp_path / "math_mod.py").write_text("def sin(): return 0\n", encoding="utf-8")
    (tmp_path / "cmath_mod.py").write_text("def sin(): return 1\n", encoding="utf-8")
    (tmp_path / "worker.py").write_text(
        """
from math_mod import sin

def run_cmath():
    from cmath_mod import sin
    return sin()

def run_math():
    return sin()
""".lstrip(),
        encoding="utf-8",
    )

    result = analyze_repository(tmp_path)
    calls = [r for r in result["relationships"] if r["type"] == "CALLS"]

    assert any(
        c["source_qualified"] == "worker.run_cmath"
        and c["target_qualified"] == "cmath_mod.sin"
        for c in calls
    )
    assert any(
        c["source_qualified"] == "worker.run_math"
        and c["target_qualified"] == "math_mod.sin"
        for c in calls
    )


def test_import_resolver_external_vs_unresolved(tmp_path):
    """ImportResolver correctly marks stdlib and 3rd-party imports as external."""
    (tmp_path / "app.py").write_text(
        """
import json
import requests
from .non_existent import missing_func
""".lstrip(),
        encoding="utf-8",
    )

    parsed = parse_repository(tmp_path)
    index = SymbolIndex(parsed["files"])
    resolver = ImportResolver(index)

    file_record = parsed["files"][0]
    imports = file_record["imports"]

    # json (stdlib) -> external
    res_json = resolver.resolve_import_alias(imports[0]["aliases"][0], file_record)
    assert res_json.status == "external"
    assert res_json.is_external is True

    # requests (third party) -> external
    res_req = resolver.resolve_import_alias(imports[1]["aliases"][0], file_record)
    assert res_req.status == "external"
    assert res_req.is_external is True

    # relative import to missing file -> unresolved
    res_missing = resolver.resolve_import_alias(imports[2]["aliases"][0], file_record)
    assert res_missing.status == "unresolved"
    assert res_missing.is_external is False


def test_fastapi_include_router_prefix_extraction(tmp_path):
    """FastAPIResolver extracts router module and prefix parameter statically."""
    (tmp_path / "routers").mkdir()
    (tmp_path / "routers" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "routers" / "items.py").write_text(
        """
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
def list_items():
    return []
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "main.py").write_text(
        """
from fastapi import FastAPI
from routers import items

app = FastAPI()
app.include_router(items.router, prefix="/api/v1/items")
""".lstrip(),
        encoding="utf-8",
    )

    result = analyze_repository(tmp_path)
    includes = [r for r in result["relationships"] if r["type"] == "INCLUDES"]
    assert len(includes) == 1
    assert includes[0]["source_qualified"] == "main"
    assert includes[0]["target_qualified"] == "routers.items"
    assert includes[0]["metadata"]["route"] == "/api/v1/items"


def test_flask_register_blueprint_prefix_extraction(tmp_path):
    """FlaskResolver extracts blueprint module and url_prefix statically."""
    (tmp_path / "blueprints").mkdir()
    (tmp_path / "blueprints" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "blueprints" / "auth.py").write_text(
        """
from flask import Blueprint
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.route("/login")
def login():
    return "login"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        """
from flask import Flask
from blueprints.auth import auth_bp

app = Flask(__name__)
app.register_blueprint(auth_bp)
""".lstrip(),
        encoding="utf-8",
    )

    result = analyze_repository(tmp_path)
    includes = [r for r in result["relationships"] if r["type"] == "INCLUDES"]
    assert len(includes) == 1
    assert includes[0]["source_qualified"] == "app"
    assert includes[0]["target_qualified"] == "blueprints.auth"
    assert includes[0]["metadata"]["route"] == "/auth"


def test_graph_validation_referential_integrity(tmp_path):
    """Full repository analysis has zero validation errors and zero dangling pointers."""
    (tmp_path / "models.py").write_text(
        """
from django.db import models

class Article(models.Model):
    title = models.CharField(max_length=100)
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "urls.py").write_text(
        """
from django.urls import include, path

urlpatterns = [
    path("auth/", include("django.contrib.auth.urls")),
]
""".lstrip(),
        encoding="utf-8",
    )

    result = analyze_repository(tmp_path)
    assert result["stats"]["validation_errors"] == 0
    assert len(result["diagnostics"]) == 0

    # Test validator directly
    entity_ids = {e["id"] for e in result["entities"]}
    for r in result["relationships"]:
        assert r["source_id"] in entity_ids, f"Dangling source: {r['source_id']}"
        assert r["target_id"] in entity_ids, f"Dangling target: {r['target_id']}"
