from pathlib import Path
import json

from cypher.analyzer.ast_parser import parse_repository

project_root = Path(__file__).resolve().parent
sample_repo_path = project_root / "sample_repo"

result = parse_repository(sample_repo_path)

print("STATS:")
print(json.dumps(result["stats"], indent=2))

print("\nFILE: users/views.py")
users_views = next(
    file for file in result["files"]
    if file["path"] == "users/views.py"
)
print(json.dumps(users_views, indent=2, ensure_ascii=False))

print("\nERRORS:")
print(json.dumps(result["errors"], indent=2, ensure_ascii=False))