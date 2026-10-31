"""Tests for cross-file symbol indexing and relationship resolution."""

from pathlib import Path

from cypher.analyzer.engine import analyze_repository


def test_same_file_function_call(tmp_path):
    (tmp_path / "mod.py").write_text(
        """
def helper():
    return 42

def caller():
    return helper()
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    calls = [r for r in res["relationships"] if r["type"] == "CALLS"]
    assert any(
        c["source_qualified"] == "mod.caller" and c["target_qualified"] == "mod.helper"
        for c in calls
    )


def test_cross_file_call_imported_module(tmp_path):
    (tmp_path / "services.py").write_text(
        """
def list_users():
    return []
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "views.py").write_text(
        """
from . import services

def user_list():
    return services.list_users()
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    calls = [r for r in res["relationships"] if r["type"] == "CALLS"]
    assert any(
        c["source_qualified"] == "views.user_list"
        and c["target_qualified"] == "services.list_users"
        for c in calls
    )


def test_cross_file_call_imported_symbol(tmp_path):
    (tmp_path / "services.py").write_text(
        """
def list_users():
    return []
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "views.py").write_text(
        """
from .services import list_users

def user_list():
    return list_users()
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    calls = [r for r in res["relationships"] if r["type"] == "CALLS"]
    assert any(
        c["source_qualified"] == "views.user_list"
        and c["target_qualified"] == "services.list_users"
        for c in calls
    )


def test_aliased_import_call(tmp_path):
    pkg = tmp_path / "users"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "services.py").write_text(
        """
def list_users():
    return []
""".lstrip(),
        encoding="utf-8",
    )
    (pkg / "views.py").write_text(
        """
import users.services as svc

def user_list():
    return svc.list_users()
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    calls = [r for r in res["relationships"] if r["type"] == "CALLS"]
    assert any(
        c["source_qualified"] == "users.views.user_list"
        and c["target_qualified"] == "users.services.list_users"
        for c in calls
    )


def test_self_method_call(tmp_path):
    (tmp_path / "client.py").write_text(
        """
class Client:
    def helper(self):
        return 1

    def load(self):
        return self.helper()
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    calls = [r for r in res["relationships"] if r["type"] == "CALLS"]
    assert any(
        c["source_qualified"] == "client.Client.load"
        and c["target_qualified"] == "client.Client.helper"
        for c in calls
    )


def test_class_inheritance(tmp_path):
    (tmp_path / "models.py").write_text(
        """
from django.db import models

class Profile(models.Model):
    pass
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    inherits = [r for r in res["relationships"] if r["type"] == "INHERITS"]
    assert any(
        i["source_qualified"] == "models.Profile"
        and "django.db.models.Model" in i["target_qualified"]
        and i["metadata"].get("external") is True
        for i in inherits
    )


def test_class_constructor_instantiates(tmp_path):
    (tmp_path / "core.py").write_text(
        """
class MyClass:
    pass

def factory():
    return MyClass()
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    instantiates = [r for r in res["relationships"] if r["type"] == "INSTANTIATES"]
    assert any(
        i["source_qualified"] == "core.factory"
        and i["target_qualified"] == "core.MyClass"
        for i in instantiates
    )


def test_recursive_call(tmp_path):
    (tmp_path / "math_ops.py").write_text(
        """
def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    calls = [r for r in res["relationships"] if r["type"] == "CALLS"]
    assert any(
        c["source_qualified"] == "math_ops.factorial"
        and c["target_qualified"] == "math_ops.factorial"
        for c in calls
    )


def test_django_include_relationship(tmp_path):
    (tmp_path / "urls.py").write_text(
        """
from django.urls import include, path

urlpatterns = [
    path("api/", include("sub_app.urls")),
]
""".lstrip(),
        encoding="utf-8",
    )
    sub = tmp_path / "sub_app"
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "urls.py").write_text("urlpatterns = []\n", encoding="utf-8")
    res = analyze_repository(tmp_path)
    includes = [r for r in res["relationships"] if r["type"] == "INCLUDES"]
    assert any(
        inc["source_qualified"] == "urls"
        and inc["target_qualified"] == "sub_app.urls"
        and inc["target_file"] == "sub_app/urls.py"
        for inc in includes
    )


def test_django_url_path_routes_to(tmp_path):
    (tmp_path / "views.py").write_text(
        """
def user_list(request):
    return "ok"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "urls.py").write_text(
        """
from django.urls import path
from . import views

urlpatterns = [
    path("users/", views.user_list, name="user_list"),
]
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    routes = [r for r in res["relationships"] if r["type"] == "ROUTES_TO"]
    assert any(
        r["source_qualified"] == "urls"
        and r["target_qualified"] == "views.user_list"
        and r["metadata"]["route"] == "users/"
        for r in routes
    )


def test_unresolved_call_in_references(tmp_path):
    (tmp_path / "foo.py").write_text(
        """
def run(handler):
    handler.unknown_method()
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    unresolved = res["unresolved_references"]
    assert any(
        u["expression"] == "handler.unknown_method"
        and u["status"] in ("unresolved", "dynamic")
        for u in unresolved
    )


def test_external_call_marked_as_external(tmp_path):
    (tmp_path / "app.py").write_text(
        """
from django.shortcuts import render

def home(request):
    return render(request, "index.html")
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    unresolved = res["unresolved_references"]
    assert any("render" in u["expression"] and u["status"] == "external" for u in unresolved)


def test_duplicate_relationship_prevention(tmp_path):
    (tmp_path / "calc.py").write_text(
        """
def add(a, b):
    return a + b

def calc():
    x = add(1, 2)
    y = add(3, 4)
    return x + y
""".lstrip(),
        encoding="utf-8",
    )
    res = analyze_repository(tmp_path)
    rel_ids = [r["id"] for r in res["relationships"]]
    assert len(rel_ids) == len(set(rel_ids))


def test_stable_ids(tmp_path):
    (tmp_path / "mod.py").write_text(
        """
def func_a():
    return 1

def func_b():
    return func_a()
""".lstrip(),
        encoding="utf-8",
    )
    res1 = analyze_repository(tmp_path)
    res2 = analyze_repository(tmp_path)
    assert [r["id"] for r in res1["relationships"]] == [r["id"] for r in res2["relationships"]]
    assert [e["id"] for e in res1["entities"]] == [e["id"] for e in res2["entities"]]


def test_full_sample_repo_analysis():
    repo_path = Path(__file__).resolve().parent.parent / "sample_repo"
    res = analyze_repository(repo_path)

    # 1. Expected ROUTES_TO
    routes = {
        (r["source_qualified"], r["target_qualified"], r["metadata"].get("route"))
        for r in res["relationships"]
        if r["type"] == "ROUTES_TO"
    }
    assert ("users.urls", "users.views.user_list", "") in routes
    assert ("users.urls", "users.views.user_create", "users/new/") in routes
    assert ("users.urls", "users.views.user_detail", "users/<int:user_id>/") in routes
    assert ("users.urls", "users.views.profile_update", "users/<int:user_id>/edit/") in routes

    # 2. Expected INCLUDES
    includes = {
        (r["source_qualified"], r["target_qualified"])
        for r in res["relationships"]
        if r["type"] == "INCLUDES"
    }
    assert ("sample_project.urls", "users.urls") in includes

    # 3. Expected CALLS
    calls = {
        (r["source_qualified"], r["target_qualified"])
        for r in res["relationships"]
        if r["type"] == "CALLS"
    }
    assert ("users.views.user_list", "users.services.list_users") in calls
    assert ("users.views.user_detail", "users.services.get_user_detail") in calls
    assert ("users.views.user_create", "users.services.create_user_with_profile") in calls
    assert ("users.views.profile_update", "users.services.get_or_create_user_profile") in calls
    assert ("users.services.list_users", "users.repository.list_users") in calls
    assert ("users.services.get_user_detail", "users.repository.get_user_by_id") in calls
    assert (
        "users.services.get_or_create_user_profile",
        "users.services.get_user_detail",
    ) in calls
    assert (
        "users.services.create_user_with_profile",
        "users.repository.create_user",
    ) in calls
    assert (
        "users.services.create_user_with_profile",
        "users.repository.get_or_create_profile",
    ) in calls
    assert (
        "users.services.create_user_with_profile",
        "users.repository.save_profile",
    ) in calls

    # 4. Expected INHERITS
    inherits = {
        (r["source_qualified"], r["target_qualified"])
        for r in res["relationships"]
        if r["type"] == "INHERITS"
    }
    assert any(
        src == "users.models.Profile" and "django.db.models.Model" in tgt
        for src, tgt in inherits
    )
