from cypher.analyzer.engine import analyze_repository
from pathlib import Path

print("=== FastAPI Sample Repo ===")
r = analyze_repository(Path("sample_fastapi_repo"))
for rel in r["relationships"]:
    m = rel.get("metadata", {})
    if rel["type"] == "ROUTES_TO":
        methods = m.get("http_methods") or []
        method_str = ",".join(methods) if methods else "?"
        route = m.get("route", "?")
        print(f"  [{method_str}] '{route}' -> {rel['target_qualified']}")
    if rel["type"] == "INCLUDES":
        print(f"  INCLUDES: {rel['source_qualified']} -> {rel['target_qualified']}")

print()
print("=== Flask Sample Repo ===")
r2 = analyze_repository(Path("sample_flask_repo"))
for rel in r2["relationships"]:
    m = rel.get("metadata", {})
    if rel["type"] == "ROUTES_TO":
        methods = m.get("http_methods") or []
        method_str = ",".join(methods) if methods else "GET"
        route = m.get("route", "?")
        print(f"  [{method_str}] '{route}' -> {rel['target_qualified']}")
    if rel["type"] == "INCLUDES":
        print(f"  INCLUDES: {rel['source_qualified']} -> {rel['target_qualified']}")
