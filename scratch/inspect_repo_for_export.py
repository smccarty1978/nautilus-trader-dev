import os
import json
from pathlib import Path

studies_dir = Path("studies")
studies_info = []

for s in sorted(studies_dir.iterdir()):
    if not s.is_dir() or s.name.startswith("."):
        continue
    
    files = list(s.rglob("*"))
    md_files = [f.name for f in files if f.suffix == ".md"]
    py_files = [f.name for f in files if f.suffix == ".py"]
    json_files = [f.name for f in files if f.suffix == ".json"]
    csv_files = [f.name for f in files if f.suffix == ".csv"]
    parquet_files = [f.name for f in files if f.suffix == ".parquet"]
    
    has_spec = any("spec" in f.lower() for f in md_files)
    has_report = any("report" in f.lower() for f in md_files)
    has_audit = any("audit" in str(f).lower() for f in files if f.suffix == ".md")
    
    studies_info.append({
        "name": s.name,
        "md_count": len(md_files),
        "py_count": len(py_files),
        "json_count": len(json_files),
        "csv_count": len(csv_files),
        "parquet_count": len(parquet_files),
        "has_spec": has_spec,
        "has_report": has_report,
        "has_audit": has_audit,
        "md_files": md_files[:5]
    })

print(f"Total studies analyzed: {len(studies_info)}")
specs_count = sum(1 for s in studies_info if s["has_spec"])
reports_count = sum(1 for s in studies_info if s["has_report"])
audits_count = sum(1 for s in studies_info if s["has_audit"])
print(f"Studies with SPEC: {specs_count}/{len(studies_info)}")
print(f"Studies with Reports: {reports_count}/{len(studies_info)}")
print(f"Studies with Audit: {audits_count}/{len(studies_info)}")
print("\nSample 15 studies:")
for s in studies_info[:15]:
    print(f"- {s['name']}: SPEC={s['has_spec']}, Report={s['has_report']}, Audits={s['has_audit']}, Py={s['py_count']}, Parquet={s['parquet_count']}, CSV={s['csv_count']}, JSON={s['json_count']}")
