"""Script to run analyze_repository on sample_repo and inspect results."""

from pathlib import Path
import json

from cypher.analyzer.engine import analyze_repository


def main() -> None:
    project_root = Path(__file__).resolve().parent
    sample_repo_path = project_root / "sample_repo"

    print("=" * 80)
    print(f"Running Cypher Static Analysis on: {sample_repo_path}")
    print("=" * 80)

    result = analyze_repository(sample_repo_path)

    # 1. Stats Summary
    print("\n--- STATS SUMMARY ---")
    print(json.dumps(result["stats"], indent=2))

    relationships = result["relationships"]

    # 2. CALLS
    calls = [r for r in relationships if r["type"] == "CALLS"]
    print(f"\n--- CALLS RELATIONSHIPS ({len(calls)}) ---")
    for r in calls:
        print(f"  {r['source_qualified']} -> {r['target_qualified']} (line {r.get('line')})")

    # 3. ROUTES_TO
    routes = [r for r in relationships if r["type"] == "ROUTES_TO"]
    print(f"\n--- ROUTES_TO RELATIONSHIPS ({len(routes)}) ---")
    for r in routes:
        meta = r.get("metadata", {})
        route_str = meta.get("route", "")
        name_str = f" [name={meta.get('url_name')}]" if meta.get("url_name") else ""
        print(f"  {r['source_qualified']} (route: '{route_str}'{name_str}) -> {r['target_qualified']} ({r['target_file']})")

    # 4. INCLUDES
    includes = [r for r in relationships if r["type"] == "INCLUDES"]
    print(f"\n--- INCLUDES RELATIONSHIPS ({len(includes)}) ---")
    for r in includes:
        meta = r.get("metadata", {})
        route_str = meta.get("route", "")
        print(f"  {r['source_qualified']} (route: '{route_str}') -> {r['target_qualified']} ({r['target_file']})")

    # 5. IMPORTS (file-level)
    imports = [r for r in relationships if r["type"] == "IMPORTS"]
    print(f"\n--- IMPORTS RELATIONSHIPS ({len(imports)}) ---")
    for r in imports:
        print(f"  {r['source_qualified']} -> {r['target_qualified']}")

    # 6. INHERITS
    inherits = [r for r in relationships if r["type"] == "INHERITS"]
    print(f"\n--- INHERITS RELATIONSHIPS ({len(inherits)}) ---")
    for r in inherits:
        ext = "external" if r.get("metadata", {}).get("external") else "internal"
        print(f"  {r['source_qualified']} -> {r['target_qualified']} ({ext})")

    # 7. INSTANTIATES
    instantiates = [r for r in relationships if r["type"] == "INSTANTIATES"]
    print(f"\n--- INSTANTIATES RELATIONSHIPS ({len(instantiates)}) ---")
    for r in instantiates:
        print(f"  {r['source_qualified']} -> {r['target_qualified']} (line {r.get('line')})")

    # 8. Unresolved References
    unresolved = result["unresolved_references"]
    print(f"\n--- UNRESOLVED REFERENCES ({len(unresolved)} total) ---")
    print("Showing first 5:")
    for u in unresolved[:5]:
        print(f"  [{u['status']}] {u['caller_qualified'] or u['caller_file']}:{u['line']} -> {u['expression']}")
        print(f"      reason: {u['reason']}")

    print("\n" + "=" * 80)
    print("Analysis complete.")
    print("=" * 80)


def _print_framework_routes(result: dict, framework_label: str) -> None:
    """Print ROUTES_TO and INCLUDES for a specific framework."""
    relationships = result["relationships"]
    routes_to = [r for r in relationships if r["type"] == "ROUTES_TO"]
    includes = [r for r in relationships if r["type"] == "INCLUDES"]

    print(f"\n--- {framework_label} ROUTES_TO ({len(routes_to)}) ---")
    for r in routes_to:
        methods = r.get("metadata", {}).get("http_methods") or []
        method_str = f" [{','.join(methods)}]" if methods else ""
        print(f"  {r['source_qualified']}{method_str} '{r.get('metadata', {}).get('route', '?')}' -> {r['target_qualified']} ({r['target_file']})")

    print(f"\n--- {framework_label} INCLUDES ({len(includes)}) ---")
    for r in includes:
        print(f"  {r['source_qualified']} -> {r['target_qualified']} ({r['target_file']})")

    stats = result["stats"]
    print(f"\n--- {framework_label} STATS ---")
    print(f"  Entities   : {stats['total_entities']}")
    print(f"  Rels       : {stats['total_relationships']}  {stats['relationships_by_type']}")
    print(f"  Unresolved : {stats.get('unresolved_calls', 0)}")


def _analyse_fastapi(project_root: Path) -> None:
    from cypher.analyzer.engine import analyze_repository

    repo = project_root / "sample_fastapi_repo"
    if not repo.exists():
        print("\n[sample_fastapi_repo not found — skipping]")
        return
    print("\n" + "=" * 80)
    print(f"Running Cypher Analysis on: {repo}")
    print("=" * 80)
    result = analyze_repository(repo)
    _print_framework_routes(result, "FASTAPI")


def _analyse_flask(project_root: Path) -> None:
    from cypher.analyzer.engine import analyze_repository

    repo = project_root / "sample_flask_repo"
    if not repo.exists():
        print("\n[sample_flask_repo not found — skipping]")
        return
    print("\n" + "=" * 80)
    print(f"Running Cypher Analysis on: {repo}")
    print("=" * 80)
    result = analyze_repository(repo)
    _print_framework_routes(result, "FLASK")


if __name__ == "__main__":
    main()
    project_root = Path(__file__).resolve().parent
    _analyse_fastapi(project_root)
    _analyse_flask(project_root)
