"""Script to run analyze_repository on sample repos and test Neo4j graph readiness."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from cypher.analyzer.engine import analyze_repository
from cypher.graph.graph_builder import GraphBuilder
from cypher.graph.neo4j_client import Neo4jClient, Neo4jConfig
from cypher.graph.queries import (
    find_all_routes,
    find_function_dependencies,
    find_uncalled_functions,
    get_repository_overview,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("check_analysis")


def run_analysis(sample_repo_path: Path, neo4j_live: bool = False) -> dict:
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
    for r in calls[:15]:
        print(f"  {r['source_qualified']} -> {r['target_qualified']} (line {r.get('line')}, method={r.get('method')})")
    if len(calls) > 15:
        print(f"  ... and {len(calls) - 15} more CALLS")

    # 3. ROUTES_TO
    routes = [r for r in relationships if r["type"] == "ROUTES_TO"]
    print(f"\n--- ROUTES_TO RELATIONSHIPS ({len(routes)}) ---")
    for r in routes:
        meta = r.get("metadata", {})
        route_str = meta.get("route", "")
        name_str = f" [name={meta.get('url_name')}]" if meta.get("url_name") else ""
        methods_str = f" [{','.join(meta.get('http_methods', []))}]" if meta.get("http_methods") else ""
        print(f"  {r['source_qualified']}{methods_str} (route: '{route_str}'{name_str}) -> {r['target_qualified']} ({r['target_file']})")

    # 4. INCLUDES
    includes = [r for r in relationships if r["type"] == "INCLUDES"]
    print(f"\n--- INCLUDES RELATIONSHIPS ({len(includes)}) ---")
    for r in includes:
        meta = r.get("metadata", {})
        route_str = meta.get("route", "")
        prefix_str = f" (prefix: '{route_str}')" if route_str else ""
        print(f"  {r['source_qualified']}{prefix_str} -> {r['target_qualified']} ({r['target_file']})")

    # 5. Graph Validation Check
    print("\n--- GRAPH REFERENTIAL INTEGRITY CHECK ---")
    val_errors = result["stats"].get("validation_errors", 0)
    if val_errors == 0:
        print("  [SUCCESS] All relationships have valid, non-dangling source and target IDs in entities.")
    else:
        print(f"  [WARNING] {val_errors} validation error(s) detected: {result.get('diagnostics', [])}")

    # 6. Neo4j Graph Builder Test (Dry-run & Live)
    print("\n--- NEO4J INGESTION TEST ---")
    builder = GraphBuilder()
    dry_summary = builder.ingest(result, dry_run=True)
    print(f"  [DRY-RUN] Ingestion Payload Ready:")
    print(f"    Nodes to MERGE        : {dry_summary['nodes_total']} {dry_summary['nodes_by_label']}")
    print(f"    Relationships to MERGE: {dry_summary['relationships_total']} {dry_summary['relationships_by_type']}")

    if neo4j_live:
        print("\n  [LIVE] Attempting connection to Neo4j...")
        client = Neo4jClient()
        if client.verify_connectivity():
            print("  [LIVE] Neo4j connection successful! Ingesting graph...")
            live_builder = GraphBuilder(client)
            live_summary = live_builder.ingest(result, dry_run=False)
            print(f"  [LIVE] Ingestion complete: {live_summary['nodes_total']} nodes, {live_summary['relationships_total']} rels.")

            # Run sample Cypher query
            overview = get_repository_overview(client)
            print(f"  [LIVE] Repository Overview from Neo4j query: {overview}")
        else:
            print("  [LIVE] Neo4j daemon not reachable. Run 'docker run -p 7687:7687 -p 7474:7474 -e NEO4J_AUTH=neo4j/password neo4j' to start.")

    return result


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
        prefix = r.get("metadata", {}).get("route", "")
        prefix_str = f" (prefix: '{prefix}')" if prefix else ""
        print(f"  {r['source_qualified']}{prefix_str} -> {r['target_qualified']} ({r['target_file']})")

    stats = result["stats"]
    print(f"\n--- {framework_label} STATS ---")
    print(f"  Entities   : {stats['total_entities']}")
    print(f"  Rels       : {stats['total_relationships']}  {stats['relationships_by_type']}")
    print(f"  Validation : {stats.get('validation_errors', 0)} errors")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cypher Static Analysis & Neo4j Ingestion Validator")
    parser.add_argument("--neo4j", action="store_true", help="Attempt live Neo4j ingestion if server reachable")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent

    # 1. Django sample repo
    sample_repo = project_root / "sample_repo"
    run_analysis(sample_repo, neo4j_live=args.neo4j)

    # 2. FastAPI sample repo
    fastapi_repo = project_root / "sample_fastapi_repo"
    if fastapi_repo.exists():
        print("\n" + "=" * 80)
        print(f"Running Cypher Analysis on: {fastapi_repo}")
        print("=" * 80)
        res_fastapi = analyze_repository(fastapi_repo)
        _print_framework_routes(res_fastapi, "FASTAPI")
        GraphBuilder().ingest(res_fastapi, dry_run=True)

    # 3. Flask sample repo
    flask_repo = project_root / "sample_flask_repo"
    if flask_repo.exists():
        print("\n" + "=" * 80)
        print(f"Running Cypher Analysis on: {flask_repo}")
        print("=" * 80)
        res_flask = analyze_repository(flask_repo)
        _print_framework_routes(res_flask, "FLASK")
        GraphBuilder().ingest(res_flask, dry_run=True)


if __name__ == "__main__":
    main()
