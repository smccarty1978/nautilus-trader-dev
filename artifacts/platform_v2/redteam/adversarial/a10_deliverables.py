"""A10: expand the DELIVERABLES templates ({a,b} and <year>) against the study the golden
end-to-end run actually produced, and confirm every declared path exists on disk."""
from __future__ import annotations
import itertools, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from research_workflow.audit_packets_v2 import deliverables_for_plan  # noqa

state = json.loads((Path(__file__).with_name("a9_a10_results.json")).read_text())
study = Path(state["study_tmp"]) / "studies" / "adv_e2e"
plan = json.loads((study / "compiled_plan.json").read_text())
dl = deliverables_for_plan(plan)
years = {"collection": [str(y) for y in plan["chronology"]["train"]],
         "oos": [str(y) for y in plan["chronology"]["dev"]]}


def expand(stage, tpl):
    outs = [tpl]
    m = re.search(r"\{([^}]*)\}", tpl)
    if m:
        outs = [tpl.replace(m.group(0), p) for p in m.group(1).split(",")]
    if "<year>" in tpl:
        outs = [o.replace("<year>", y) for o in outs for y in years.get(stage, [])]
    return outs


rows, missing = [], []
for stage, tpls in dl.items():
    for tpl in tpls:
        for p in expand(stage, tpl):
            exists = (study / p).exists()
            rows.append({"stage": stage, "template": tpl, "path": p, "exists": exists})
            if not exists:
                missing.append({"stage": stage, "path": p})

print("study:", study)
print(json.dumps(rows, indent=1))
print("\nMISSING:", json.dumps(missing, indent=1))
verdict = "BLOCKED" if not missing else "BYPASSED"
print("\nA10 verdict:", verdict)
Path(__file__).with_name("a10_results.json").write_text(json.dumps(
    {"rows": rows, "missing": missing, "verdict": verdict, "study": str(study)}, indent=1))
