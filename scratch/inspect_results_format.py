import os
import json
from pathlib import Path

studies_dir = Path("studies")

print("--- Checking JSON Result Files ---")
json_samples = []
for p in studies_dir.rglob("*.json"):
    # Avoid lint.json or huge files
    if "results" in str(p) or "summary" in str(p) or "metrics" in str(p) or "baseline" in str(p):
        json_samples.append(p)

print(f"Total matching result JSONs: {len(json_samples)}")
for p in json_samples[:5]:
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            keys = list(data.keys()) if isinstance(data, dict) else f"list of len {len(data)}"
            print(f"  {p}: {keys}")
    except Exception as e:
        print(f"  {p}: Error reading {e}")

print("\n--- Checking Report MD Headers ---")
report_samples = []
for p in studies_dir.rglob("*.md"):
    name = p.name.lower()
    if "report" in name or "spec" in name or "final" in name:
        report_samples.append(p)

print(f"Total matching report/spec MDs: {len(report_samples)}")
for p in report_samples[:8]:
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = [f.readline().strip() for _ in range(5)]
            print(f"  {p.relative_to(studies_dir)}:")
            for l in lines:
                if l:
                    print(f"    {l}")
    except Exception as e:
        print(f"  {p}: Error {e}")
