"""NEW ATTACK N5 (pass 03): W-5 added V2Options.model_root. Probe its BOUNDARY -- every place a
governed v2 run can still reach the operator's real durable store: the out-of-process partition
child (`python -m research_workflow.lifecycle_v2 partition`, which builds its own V2Options), the
tuning/ledger path, and any model-store call site in lifecycle_v2 that does not forward the option.
Read-only w.r.t. the real store: it is snapshotted, never written."""
from __future__ import annotations
import ast, inspect, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
import research_workflow.lifecycle_v2 as LC  # noqa
from research_workflow.roots import resolve_model_root  # noqa

res = []


def rec(case, outcome, verdict):
    res.append({"case": case, "outcome": str(outcome)[:400], "verdict": verdict})
    print(f"[{verdict}] {case}\n    {str(outcome)[:400]}")


REAL = Path(resolve_model_root())
before = sorted(p.name for p in (REAL / "models").iterdir()) if (REAL / "models").is_dir() else []

# ---- N5a: the partition child CLI has no --model-root; its V2Options defaults to the real store ----
main_src = inspect.getsource(LC.main)
has_flag = "--model-root" in main_src or "model_root" in main_src
rec("N5a out-of-process partition child (`-m research_workflow.lifecycle_v2 partition`) forwards model_root",
    f"child V2Options construction: {[l.strip() for l in main_src.splitlines() if 'V2Options(' in l]}; "
    f"--model-root flag present: {has_flag}",
    "BLOCKED" if has_flag else "BYPASSED")

# ---- N5b: does the partition path actually reach the model store today? ----
src = (ROOT / "research_workflow" / "lifecycle_v2.py").read_text(encoding="utf-8")
tree = ast.parse(src)
store_names = {"store_model", "authenticate_model", "read_manifest", "score", "record_fit", "list_store",
               "model_dir", "resolve", "validate_golden"}
fn_calls = {}
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        hits = []
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                f = sub.func
                name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
                if name in store_names and name in {"store_model", "authenticate_model", "read_manifest", "score", "record_fit"}:
                    kw = {k.arg for k in sub.keywords}
                    pos = len(sub.args)
                    forwarded = ("model_root" in kw) or (name == "read_manifest" and pos >= 2)
                    hits.append({"call": name, "forwards_model_root": forwarded, "line": sub.lineno})
        if hits:
            fn_calls[node.name] = hits
unforwarded = {fn: [h for h in hs if not h["forwards_model_root"]] for fn, hs in fn_calls.items()}
unforwarded = {fn: hs for fn, hs in unforwarded.items() if hs}
rec("N5b every model-store call inside lifecycle_v2 forwards opts.model_root",
    f"call sites by function: {json.dumps(fn_calls)}; NOT forwarding: {json.dumps(unforwarded)}",
    "BLOCKED" if not unforwarded else "BYPASSED")

# ---- N5c: run_partition (the child's entry point) must not touch the model store at all ----
part_src = inspect.getsource(LC.V2Lifecycle.run_partition)
touches = sorted(n for n in store_names if n in part_src)
rec("N5c run_partition (executed in the child with model_root=None) touches no model-store API",
    f"model-store names appearing in run_partition: {touches}",
    "BLOCKED" if not touches else "BYPASSED")

# ---- N5d: is model_root reachable from the operator CLI at all? ----
cli = (ROOT / "scripts" / "research.py").read_text(encoding="utf-8")
rec("N5d scripts/research.py exposes --model-root for v2 runs",
    f"'model_root' in scripts/research.py: {'model_root' in cli} (absent => production runs keep using the "
    f"configured durable store, which is the intended default)",
    "BLOCKED" if "model_root" in cli else "NOTE")

# ---- N5e: the real store did not move during this pass ----
after = sorted(p.name for p in (REAL / "models").iterdir()) if (REAL / "models").is_dir() else []
rec("N5e the operator's real model store is unchanged by this audit pass",
    f"root={REAL} before={len(before)} after={len(after)} added={sorted(set(after) - set(before))} "
    f"removed={sorted(set(before) - set(after))}",
    "BLOCKED" if before == after else "BYPASSED")

print("\n=== RESULTS ===")
print(json.dumps(res, indent=1))
Path(__file__).with_name("n5_results.json").write_text(json.dumps(res, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] == "BYPASSED"], indent=1))
