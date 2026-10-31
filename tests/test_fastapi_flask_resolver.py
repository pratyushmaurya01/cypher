"""Tests for FastAPI and Flask route resolvers."""

from __future__ import annotations

from pathlib import Path

import pytest

from cypher.analyzer.ast_parser import parse_repository
from cypher.analyzer.engine import analyze_repository
from cypher.resolver.fastapi_resolver import FastAPIResolver
from cypher.resolver.flask_resolver import FlaskResolver
from cypher.resolver.import_resolver import ImportResolver
from cypher.resolver.symbol_index import SymbolIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build(tmp_path: Path, files: dict[str, str]):
    """Write files into tmp_path and parse the repo."""
    for rel, src in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    result = parse_repository(tmp_path)
    files_list = result["files"]
    index = SymbolIndex(files_list)
    import_resolver = ImportResolver(index)
    return files_list, index, import_resolver


def _rel_types(rels, rel_type):
    return [r for r in rels if r["rel_type"] == rel_type]


def _targets(rels, rel_type):
    return {r.target_qualified for r in rels if r.rel_type == rel_type}


# ===========================================================================
# FastAPI Tests
# ===========================================================================


def test_fastapi_direct_app_route(tmp_path):
    """@app.get() on a FastAPI() instance produces a ROUTES_TO relationship."""
    files, index, imp = _build(tmp_path, {
        "main.py": (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n\n"
            "@app.get('/users')\n"
            "def list_users():\n"
            "    return []\n"
        )
    })
    resolver = FastAPIResolver(index, imp)
    routes = resolver.resolve_routes(files)
    assert any(r.rel_type == "ROUTES_TO" for r in routes), "Expected at least one ROUTES_TO"
    assert any(r.target_qualified and "list_users" in r.target_qualified for r in routes)
    assert any(r.route == "/users" for r in routes)


def test_fastapi_router_routes(tmp_path):
    """@router.get() on an APIRouter produces ROUTES_TO relationships."""
    files, index, imp = _build(tmp_path, {
        "routers/__init__.py": "",
        "routers/users.py": (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n\n"
            "@router.get('/')\n"
            "def list_users():\n"
            "    return []\n\n"
            "@router.post('/')\n"
            "async def create_user():\n"
            "    return {}\n"
        )
    })
    resolver = FastAPIResolver(index, imp)
    routes = resolver.resolve_routes(files)
    targets = {r.target_qualified for r in routes if r.rel_type == "ROUTES_TO"}
    assert any("list_users" in t for t in targets)
    assert any("create_user" in t for t in targets)


def test_fastapi_route_http_methods_captured(tmp_path):
    """HTTP methods are included in the evidence string."""
    files, index, imp = _build(tmp_path, {
        "api.py": (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n\n"
            "@app.post('/items')\n"
            "def create_item():\n"
            "    return {}\n"
        )
    })
    resolver = FastAPIResolver(index, imp)
    routes = resolver.resolve_routes(files)
    assert routes, "Expected at least one route"
    route = routes[0]
    assert "POST" in route.evidence.upper()


def test_fastapi_include_router_detected(tmp_path):
    """include_router() calls are detected as INCLUDES relationships."""
    files, index, imp = _build(tmp_path, {
        "routers/__init__.py": "",
        "routers/items.py": (
            "from fastapi import APIRouter\n"
            "router = APIRouter()\n\n"
            "@router.get('/')\n"
            "def list_items():\n"
            "    return []\n"
        ),
        "main.py": (
            "from fastapi import FastAPI\n"
            "from routers import items\n"
            "app = FastAPI()\n"
            "app.include_router(items.router, prefix='/items')\n"
        ),
    })
    resolver = FastAPIResolver(index, imp)
    includes = resolver.resolve_includes(files)
    assert includes, "Expected at least one INCLUDES relationship from include_router()"
    assert all(r.rel_type == "INCLUDES" for r in includes)


def test_fastapi_no_crash_on_non_fastapi_repo(tmp_path):
    """Resolver returns empty list when repo has no FastAPI code."""
    files, index, imp = _build(tmp_path, {
        "utils.py": "def helper():\n    pass\n"
    })
    resolver = FastAPIResolver(index, imp)
    result = resolver.resolve_all(files)
    assert result == []


def test_fastapi_sample_repo_analysis():
    """Full analyze_repository on sample_fastapi_repo produces correct ROUTES_TO."""
    repo = Path(__file__).resolve().parents[1] / "sample_fastapi_repo"
    if not repo.exists():
        pytest.skip("sample_fastapi_repo not found")

    result = analyze_repository(repo)
    routes_to = [r for r in result["relationships"] if r["type"] == "ROUTES_TO"]
    targets = {r["target_qualified"] for r in routes_to}

    # Functions defined in routers/users.py and main.py
    assert any("list_users" in t for t in targets), f"list_users not in {targets}"
    assert any("health_check" in t for t in targets), f"health_check not in {targets}"


# ===========================================================================
# Flask Tests
# ===========================================================================


def test_flask_app_route(tmp_path):
    """@app.route() on a Flask() instance produces a ROUTES_TO relationship."""
    files, index, imp = _build(tmp_path, {
        "app.py": (
            "from flask import Flask\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/users')\n"
            "def list_users():\n"
            "    return []\n"
        )
    })
    resolver = FlaskResolver(index, imp)
    routes = resolver.resolve_routes(files)
    assert any(r.rel_type == "ROUTES_TO" for r in routes)
    assert any(r.target_qualified and "list_users" in r.target_qualified for r in routes)
    assert any(r.route == "/users" for r in routes)


def test_flask_blueprint_routes(tmp_path):
    """@bp.route() on a Blueprint produces ROUTES_TO relationships."""
    files, index, imp = _build(tmp_path, {
        "blueprints/__init__.py": "",
        "blueprints/users.py": (
            "from flask import Blueprint\n"
            "users_bp = Blueprint('users', __name__)\n\n"
            "@users_bp.route('/')\n"
            "def list_users():\n"
            "    return []\n\n"
            "@users_bp.route('/<int:user_id>', methods=['GET', 'PUT'])\n"
            "def user_detail(user_id):\n"
            "    return {}\n"
        )
    })
    resolver = FlaskResolver(index, imp)
    routes = resolver.resolve_routes(files)
    targets = {r.target_qualified for r in routes if r.rel_type == "ROUTES_TO"}
    assert any("list_users" in t for t in targets)
    assert any("user_detail" in t for t in targets)


def test_flask_route_has_endpoint_name(tmp_path):
    """Flask routes use the function name as url_name."""
    files, index, imp = _build(tmp_path, {
        "app.py": (
            "from flask import Flask\n"
            "app = Flask(__name__)\n\n"
            "@app.route('/health')\n"
            "def health():\n"
            "    return 'ok'\n"
        )
    })
    resolver = FlaskResolver(index, imp)
    routes = resolver.resolve_routes(files)
    assert routes
    assert routes[0].url_name == "health"


def test_flask_register_blueprint_detected(tmp_path):
    """register_blueprint() calls are detected as INCLUDES relationships."""
    files, index, imp = _build(tmp_path, {
        "blueprints/__init__.py": "",
        "blueprints/users.py": (
            "from flask import Blueprint\n"
            "users_bp = Blueprint('users', __name__)\n\n"
            "@users_bp.route('/')\n"
            "def list_users():\n"
            "    return []\n"
        ),
        "app.py": (
            "from flask import Flask\n"
            "from blueprints.users import users_bp\n"
            "app = Flask(__name__)\n"
            "app.register_blueprint(users_bp)\n"
        ),
    })
    resolver = FlaskResolver(index, imp)
    includes = resolver.resolve_blueprints(files)
    assert includes, "Expected at least one INCLUDES from register_blueprint()"
    assert all(r.rel_type == "INCLUDES" for r in includes)


def test_flask_no_crash_on_non_flask_repo(tmp_path):
    """Resolver returns empty list when repo has no Flask code."""
    files, index, imp = _build(tmp_path, {
        "utils.py": "def helper():\n    pass\n"
    })
    resolver = FlaskResolver(index, imp)
    result = resolver.resolve_all(files)
    assert result == []


def test_flask_sample_repo_analysis():
    """Full analyze_repository on sample_flask_repo produces correct ROUTES_TO."""
    repo = Path(__file__).resolve().parents[1] / "sample_flask_repo"
    if not repo.exists():
        pytest.skip("sample_flask_repo not found")

    result = analyze_repository(repo)
    routes_to = [r for r in result["relationships"] if r["type"] == "ROUTES_TO"]
    targets = {r["target_qualified"] for r in routes_to}

    assert any("list_users" in t for t in targets), f"list_users not found in {targets}"
    assert any("health" in t for t in targets), f"health not found in {targets}"
    assert any("user_detail" in t for t in targets), f"user_detail not found in {targets}"


# ===========================================================================
# Cross-framework: both in same test run
# ===========================================================================


def test_both_resolvers_coexist_with_django(tmp_path):
    """FastAPI and Flask resolvers return empty for a Django repo — no interference."""
    django_repo = Path(__file__).resolve().parents[1] / "sample_repo"
    if not django_repo.exists():
        pytest.skip("sample_repo not found")
    result = parse_repository(django_repo)
    files_list = result["files"]
    index = SymbolIndex(files_list)
    imp = ImportResolver(index)

    fastapi_routes = FastAPIResolver(index, imp).resolve_all(files_list)
    flask_routes = FlaskResolver(index, imp).resolve_all(files_list)

    assert fastapi_routes == [], "FastAPI resolver should return nothing for Django repo"
    assert flask_routes == [], "Flask resolver should return nothing for Django repo"


def test_method_field_set_correctly_in_full_analysis():
    """ROUTES_TO relationships from FastAPI have method='fastapi_route'."""
    repo = Path(__file__).resolve().parents[1] / "sample_fastapi_repo"
    if not repo.exists():
        pytest.skip("sample_fastapi_repo not found")
    result = analyze_repository(repo)
    fastapi_routes = [
        r for r in result["relationships"]
        if r["type"] == "ROUTES_TO" and r.get("method") == "fastapi_route"
    ]
    assert fastapi_routes, "Expected ROUTES_TO with method='fastapi_route'"


def test_flask_method_field_in_full_analysis():
    """ROUTES_TO relationships from Flask have method='flask_route'."""
    repo = Path(__file__).resolve().parents[1] / "sample_flask_repo"
    if not repo.exists():
        pytest.skip("sample_flask_repo not found")
    result = analyze_repository(repo)
    flask_routes = [
        r for r in result["relationships"]
        if r["type"] == "ROUTES_TO" and r.get("method") == "flask_route"
    ]
    assert flask_routes, "Expected ROUTES_TO with method='flask_route'"
