"""Per-class durations from the measured per-test timings: sum of per-file seconds over each derived surface."""
import json, collections, os, sys
S = os.path.dirname(os.path.abspath(__file__))


def per_file(path):
    per = collections.defaultdict(float); fin = None; last = None; outcomes = collections.Counter(); nodes = collections.defaultdict(list)
    for line in open(path, encoding="utf-8"):
        d = json.loads(line)
        if "nodeid" in d:
            f = d["nodeid"].split("::")[0]; per[f] += d["seconds"]; last = d
            if d["phase"] == "call" or (d["phase"] == "setup" and d["outcome"] != "passed"):
                outcomes[d["outcome"]] += 1
                if d["outcome"] != "passed": nodes[f].append(d["nodeid"])
        else:
            fin = d
    return per, fin, last, outcomes, nodes


broad, fin, last, outcomes, failed = per_file(os.path.join(S, "broad_timing.jsonl"))
total = sum(broad.values()); wall = fin["wall"] if fin else (last["t"] if last else None)
print(f"broad: files={len(broad)} sum_test_seconds={total:.0f} wall={wall} finished={bool(fin)} outcomes={dict(outcomes)}")
two_scope = sum(v for f, v in broad.items() if f.startswith(("research_workflow/tests", "scripts/tests")))
print(f"  2-scope (research_workflow/tests scripts/tests) sum={two_scope:.0f}s = {two_scope/60:.1f} min")
print("  slowest files:")
for f, s in sorted(broad.items(), key=lambda x: -x[1])[:12]:
    print(f"    {s:8.1f}s  {f}")
missing = set()


def surface_seconds(files):
    s = 0.0
    for f in files:
        if f in broad: s += broad[f]
        else: missing.add(f)
    return s


rows = []
for name, label in (("synth_synthA", "ADDITIVE: new tracker (fixture A)"), ("synth_synthC", "ADDITIVE: new analysis op (fixture C)"),
                    ("synth_synthB", "ADDITIVE: new feature definition (fixture B)"), ("synth_synthB2", "ADDITIVE: new provider family (fixture B2)"),
                    ("synth_synthBatch", "ADDITIVE batch A+B+B2+C")):
    d = json.load(open(os.path.join(S, f"{name}.json"), encoding="utf-8"))
    rows.append((label, len(d["surface"]), d["surface_tests"], surface_seconds(d["surface"])))
rep = json.load(open(os.path.join(S, "replay.json"), encoding="utf-8"))
for r in rep:
    if r["class"] != "CORE_SURFACE" or r["sha"] in ("a7f932b0", "122c6f1a", "474cd650", "8b3d3d2f", "6624a3ea"):
        rows.append((f"{r['class']} (hist. {r['sha']} {r['label'][:40]})", r["derived_surface_files"], r["derived_surface_tests"], surface_seconds(r["surface"])))
print()
print("| surface | test files | tests | measured seconds | minutes | vs broad sum |")
print("|---|---:|---:|---:|---:|---:|")
print(f"| BROAD five scopes (this measurement) | {len(broad)} | {sum(outcomes.values())} | {total:.0f} | {total/60:.1f} | 100 % |")
print(f"| BROAD two scopes (recorded 74m41s scope) | | | {two_scope:.0f} | {two_scope/60:.1f} | {100*two_scope/total:.0f} % |")
for label, nf, nt, sec in rows:
    print(f"| {label} | {nf} | {nt} | {sec:.0f} | {sec/60:.1f} | {100*sec/total:.0f} % |")
if missing:
    print("\nsurface files without a timing record (new fixture tests / not in this run):", sorted(missing))
# surface A direct measurement
pA = os.path.join(S, "surfaceA_timing.jsonl")
if os.path.exists(pA):
    a, finA, lastA, outA, failedA = per_file(pA)
    print(f"\nsurface A direct run: files={len(a)} sum={sum(a.values()):.0f}s wall={finA['wall'] if finA else lastA['t']} finished={bool(finA)} outcomes={dict(outA)}")
    for f, ns in failedA.items():
        for n in ns: print("   FAIL", n)
print("\nbroad failures by file:")
for f, ns in sorted(failed.items()):
    print(f"  {len(ns):3d} {f}")
