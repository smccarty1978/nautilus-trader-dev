"""P6 gate: re-resolve every feature instance of every tracked compiled_study.json; emit a digest."""
import hashlib, json, subprocess, sys
from pathlib import Path
ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from features.registry import resolve_feature_request
files = subprocess.run(["git", "ls-files", "studies/*/compiled_study.json"], capture_output=True, text=True, cwd=ROOT).stdout.split()
rows = []
for f in sorted(files):
    c = json.loads((ROOT / f).read_text(encoding="utf-8"))
    study = Path(f).parent.name
    for inst in c["contracts"]["feature_contract"].get("resolved_feature_instances") or []:
        try:
            now = resolve_feature_request(inst["canonical_name"], inst.get("parameters"), physical_alias=inst.get("physical_alias"))
            now = {k: now[k] for k in ("canonical_name", "parameters", "physical_alias", "provider", "required_streams", "status") if k in now}
        except Exception as exc:
            now = {"error": f"{type(exc).__name__}: {exc}"}
        rows.append({"study": study, "requested": inst["canonical_name"], "recorded_alias": inst.get("physical_alias"), "now": now})
digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if out: out.write_text(json.dumps(rows, indent=1, sort_keys=True), encoding="utf-8")
print(json.dumps({"plans": len(files), "instances": len(rows), "errors": sum(1 for r in rows if "error" in r["now"]), "digest": digest}))
