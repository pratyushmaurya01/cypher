import hashlib
import json
from pathlib import Path

import pytest

from cypher.analyzer.ast_parser import parse_repository


def _file(result, path):
    return next(item for item in result["files"] if item["path"] == path)


def test_recursive_scan_and_module_names(tmp_path):
    (tmp_path / "pkg" / "nested").mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text('"""Package docs."""\n', encoding="utf-8")
    (tmp_path / "pkg" / "nested" / "mod.py").write_text(
        '"""Module docs."""\nVALUE = 2\n', encoding="utf-8"
    )

    result = parse_repository(tmp_path)

    package = _file(result, "pkg/__init__.py")
    module = _file(result, "pkg/nested/mod.py")
    assert package["module"] == "pkg"
    assert package["is_package"] is True
    assert package["docstring"] == "Package docs."
    assert module["module"] == "pkg.nested.mod"
    assert module["is_package"] is False
    assert module["line_count"] == 2
    assert module["sha256"] == hashlib.sha256(
        (tmp_path / "pkg" / "nested" / "mod.py").read_bytes()
    ).hexdigest()
    assert module["globals"][0]["name"] == "VALUE"
    assert module["globals"][0]["is_constant"] is True
    assert module["globals"][0]["value"] == "2"


def test_functions_async_nested_and_lambda_calls(tmp_path):
    (tmp_path / "module.py").write_text(
        """
def outer(value: int = 3) -> int:
    def inner():
        return helper(value)
    callback = lambda item: convert(item)
    return inner()

async def fetch(client):
    return await client.load()

def stream():
    yield 1
""".lstrip(),
        encoding="utf-8",
    )

    result = parse_repository(tmp_path)
    record = _file(result, "module.py")
    functions = {item["qualified_name"]: item for item in record["functions"]}
    assert {"outer", "outer.inner", "outer.<lambda:1>", "fetch"} <= set(functions)
    assert functions["outer"]["arguments"][0] == {
        "name": "value",
        "kind": "positional",
        "annotation": "int",
        "default": "3",
    }
    assert functions["fetch"]["kind"] == "async_function"
    assert functions["stream"]["is_generator"] is True
    assert functions["outer.inner"]["parent_function"] == "outer"
    assert any(call["caller"] == "outer.<lambda:1>" for call in record["calls"])


def test_classes_methods_nested_classes_and_attributes(tmp_path):
    (tmp_path / "models.py").write_text(
        """
class Parent:
    label: str = "parent"

    def method(self):
        return 1

    class Child:
        count = 2
""".lstrip(),
        encoding="utf-8",
    )

    record = _file(parse_repository(tmp_path), "models.py")
    parent, child = record["classes"]
    assert parent["qualified_name"] == "Parent"
    assert parent["methods"] == ["Parent.method"]
    assert parent["nested_classes"] == ["Parent.Child"]
    assert parent["attributes"][0]["value"] == "'parent'"
    assert child["parent_class"] == "Parent"
    assert child["attributes"][0]["value"] == "2"


def test_import_forms_and_condition_context(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "mod.py").write_text(
        """
import os as operating_system
from collections import defaultdict as mapping
from .helper import thing
from . import *
if enabled:
    import optional
if TYPE_CHECKING:
    from typing import Protocol
else:
    import runtime_only
""".lstrip(),
        encoding="utf-8",
    )

    imports = _file(parse_repository(tmp_path), "pkg/mod.py")["imports"]
    by_line = {item["line"]: item for item in imports}
    assert by_line[1]["aliases"][0]["alias"] == "operating_system"
    assert by_line[2]["aliases"][0]["resolved_module"] == "collections"
    assert by_line[3]["aliases"][0]["resolved_module"] == "pkg.helper.thing"
    assert by_line[4]["aliases"][0]["name"] == "*"
    assert by_line[6]["conditional"] is True
    assert by_line[8]["conditional"] is True
    assert by_line[8]["type_checking"] is True
    assert by_line[10]["conditional"] is True
    assert by_line[10]["type_checking"] is False


def test_calls_include_decorators_comprehensions_and_callers(tmp_path):
    source = """
@register(build())
def run(items):
    return [transform(item) for item in items if allowed(item)]

class Client:
    @decorate(factory())
    def load(self):
        return self.repo.save(requests.get("url"))
""".lstrip()
    (tmp_path / "calls.py").write_text(source, encoding="utf-8")

    record = _file(parse_repository(tmp_path), "calls.py")
    calls = record["calls"]
    names = {call["name"] for call in calls}
    assert {
        "register",
        "build",
        "transform",
        "allowed",
        "decorate",
        "factory",
        "self.repo.save",
        "requests.get",
    } <= names
    save_call = next(call for call in calls if call["name"] == "self.repo.save")
    assert save_call["base_name"] == "save"
    assert save_call["receiver"] == "self.repo"
    assert save_call["caller"] == "Client.load"
    assert save_call["line"] == 8
    assert save_call["column"] > 0


def test_syntax_error_is_reported_without_stopping_scan(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "good.py").write_text("def working():\n    return True\n", encoding="utf-8")

    result = parse_repository(tmp_path)

    assert result["stats"]["failed_files"] == 1
    assert result["stats"]["parsed_files"] == 1
    assert result["errors"][0]["path"] == "bad.py"
    assert result["errors"][0]["error_type"] == "SyntaxError"
    assert result["errors"][0]["line"] == 1
    assert _file(result, "good.py")["functions"][0]["name"] == "working"


def test_encoding_empty_null_and_ignored_directories(tmp_path):
    (tmp_path / "empty.py").write_bytes(b"")
    (tmp_path / "bad_encoding.py").write_bytes(b"\xff")
    (tmp_path / "null.py").write_bytes(b"value = 1\x00\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "hidden.py").write_text("hidden = True\n", encoding="utf-8")
    (tmp_path / "venv" / "Lib").mkdir(parents=True)
    (tmp_path / "venv" / "Lib" / "installed.py").write_text("pass\n", encoding="utf-8")

    result = parse_repository(tmp_path)

    assert {item["path"] for item in result["files"]} == {"empty.py"}
    assert result["stats"]["skipped_files"] == 2
    assert result["stats"]["failed_files"] == 2
    assert {error["path"] for error in result["errors"]} == {
        "bad_encoding.py",
        "null.py",
    }


def test_framework_hints(tmp_path):
    (tmp_path / "frameworks.py").write_text(
        """
from fastapi import FastAPI
from django.db import models
import click
app = FastAPI()

@app.get("/users")
def users():
    return []

class User(models.Model):
    name = models.CharField(max_length=20)

urlpatterns = [path("users/", users)]

@click.command()
def cli():
    pass

def test_users():
    assert True

from flask import Flask
flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return "ok"

from celery import shared_task

@shared_task
def refresh():
    return True

import typer
cli_app = typer.Typer()

@cli_app.command()
def inspect():
    return None
""".lstrip(),
        encoding="utf-8",
    )

    hints = _file(parse_repository(tmp_path), "frameworks.py")["framework_hints"]
    observed = {(item["framework"], item["kind"]) for item in hints}
    assert {
        ("fastapi", "route"),
        ("django", "model"),
        ("django", "url_patterns"),
        ("django", "url_pattern"),
        ("click", "command"),
        ("pytest", "test"),
        ("flask", "route"),
        ("celery", "task"),
        ("typer", "command"),
    } <= observed


def test_deterministic_json_serializable_and_read_only(tmp_path):
    source_file = tmp_path / "values.py"
    source = '"""Docs."""\nVALUE = [1, 2, 3]\n'
    source_file.write_text(source, encoding="utf-8")
    original_bytes = source_file.read_bytes()

    first = parse_repository(tmp_path)
    second = parse_repository(tmp_path)

    assert first == second
    json.dumps(first)
    assert source_file.read_bytes() == original_bytes
    assert first["stats"]["functions"] == 0
    assert first["stats"]["classes"] == 0
    assert first["stats"]["imports"] == 0
    assert first["stats"]["calls"] == 0


def test_duplicate_definitions_have_stable_unique_ids(tmp_path):
    source_file = tmp_path / "duplicate.py"
    source_file.write_text(
        "def same():\n    pass\n\ndef same():\n    pass\n",
        encoding="utf-8",
    )

    first = parse_repository(tmp_path)
    second = parse_repository(tmp_path)
    ids = [item["id"] for item in _file(first, "duplicate.py")["functions"]]

    assert len(ids) == len(set(ids)) == 2
    assert ids == [
        item["id"] for item in _file(second, "duplicate.py")["functions"]
    ]
    source_file.write_text(
        "# shifted source lines\n" + source_file.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    shifted_ids = [
        item["id"]
        for item in _file(parse_repository(tmp_path), "duplicate.py")["functions"]
    ]
    assert shifted_ids == ids


def test_oversized_file_is_skipped(tmp_path, monkeypatch):
    source_file = tmp_path / "large.py"
    source_file.write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr("cypher.analyzer.ast_parser.DEFAULT_MAX_FILE_SIZE", 1)

    result = parse_repository(tmp_path)

    assert result["stats"]["skipped_files"] == 1
    assert result["stats"]["scanned_files"] == 0
    assert result["errors"][0]["error_type"] == "FileTooLargeError"


def test_smoke_parse_actual_django_sample_repo():
    project_root = Path(__file__).resolve().parents[1]
    sample_root = project_root / "sample_repo"

    result = parse_repository(sample_root)

    assert result["stats"]["parsed_files"] > 0
    users_views = _file(result, "users/views.py")
    assert "users.views" == users_views["module"]
    assert any(function["name"] == "user_list" for function in users_views["functions"])
    assert users_views["calls"]
