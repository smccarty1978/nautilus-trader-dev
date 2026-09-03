"""A1 (CRIT-1): --years role-authority expansion attacks against lifecycle_v2.authorized_years
and the V2Lifecycle stage wiring. Independent of research_workflow/tests/*."""
from __future__ import annotations
import json, sys, tempfile, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
from research_workflow.lifecycle_v2 import authorized_years, LifecycleV2Error, V2Lifecycle, V2Options  # noqa

PLAN = {"chronology": {"train": [2029, 2030], "dev": [2031], "prohibited": [2032]}}
AUTH_OK = {"train_years": [2029, 2030], "oos_years": [2031], "prohibited_years": [2032]}

results = []
def attack(name, fn, expect_reject=True):
    try:
        out = fn()
        ok = not expect_reject
        results.append({"case": name, "outcome": f"RETURNED {out!r}", "verdict": "BLOCKED" if ok else "BYPASSED"})
    except Exception as exc:
        code = str(exc).split(":")[0]
        results.append({"case": name, "outcome": f"{type(exc).__name__}: {str(exc)[:160]}",
                        "verdict": "BLOCKED" if expect_reject else "UNEXPECTED_REJECT", "code": code})

# --- core role authority ---
attack("oos requests a TRAIN year (2029)", lambda: authorized_years(PLAN, "oos", [2029]))
attack("oos requests train+dev [2029,2031]", lambda: authorized_years(PLAN, "oos", [2029, 2031]))
attack("train requests a DEV year (2031)", lambda: authorized_years(PLAN, "train", [2031]))
attack("train requests prohibited year (2032)", lambda: authorized_years(PLAN, "train", [2032]))
attack("oos requests prohibited year (2032)", lambda: authorized_years(PLAN, "oos", [2032]))
attack("train requests an undeclared year (2044)", lambda: authorized_years(PLAN, "train", [2044]))
attack("train requests empty list []", lambda: authorized_years(PLAN, "train", []))
attack("train requests () empty tuple", lambda: authorized_years(PLAN, "train", ()))
attack("train requests non-numeric string ['twenty29']", lambda: authorized_years(PLAN, "train", ["twenty29"]))
attack("train requests None-in-list", lambda: authorized_years(PLAN, "train", [None]))
attack("train requests float 2029.9 (truncation smuggle)", lambda: authorized_years(PLAN, "train", [2029.9]))
attack("train requests bool True (int subclass -> 1)", lambda: authorized_years(PLAN, "train", [True]))
attack("unknown period 'prohibited'", lambda: authorized_years(PLAN, "prohibited", [2032]))
attack("unknown period 'all'", lambda: authorized_years(PLAN, "all", None))
# legal narrowings must NOT be rejected
attack("train narrows to [2029] (legal)", lambda: authorized_years(PLAN, "train", [2029]), expect_reject=False)
attack("train dup ['2030', 2030] normalizes (legal)", lambda: authorized_years(PLAN, "train", ["2030", 2030]), expect_reject=False)
attack("train requested=None -> role years (legal)", lambda: authorized_years(PLAN, "train", None), expect_reject=False)
attack("oos requested=None -> dev years (legal)", lambda: authorized_years(PLAN, "oos", None), expect_reject=False)
attack("dev alias == oos (legal)", lambda: authorized_years(PLAN, "dev", [2031]), expect_reject=False)

# --- authorization-artifact drift ---
attack("auth artifact has extra train year 2028 not in plan",
       lambda: authorized_years(PLAN, "train", [2029], authorization={**AUTH_OK, "train_years": [2028, 2029, 2030]}))
attack("plan has year the auth artifact lacks (auth train=[2029])",
       lambda: authorized_years(PLAN, "train", [2030], authorization={**AUTH_OK, "train_years": [2029]}))
attack("auth artifact oos_years=[2029] (train year smuggled into oos role)",
       lambda: authorized_years(PLAN, "oos", [2031], authorization={**AUTH_OK, "oos_years": [2029]}))
attack("auth artifact drops prohibited 2032",
       lambda: authorized_years(PLAN, "train", [2029], authorization={**AUTH_OK, "prohibited_years": []}))
attack("auth artifact matches plan (legal)",
       lambda: authorized_years(PLAN, "train", [2029], authorization=AUTH_OK), expect_reject=False)
# adjacent: empty authorization dict (missing keys) -- does it fail closed?
attack("authorization={} (all keys missing)", lambda: authorized_years(PLAN, "train", [2029], authorization={}))
# adjacent: prohibited year ALSO listed in train role in the plan
attack("plan lists 2032 in BOTH train and prohibited",
       lambda: authorized_years({"chronology": {"train": [2029, 2032], "dev": [2031], "prohibited": [2032]}}, "train", [2032]))
attack("plan lists 2032 in BOTH train and prohibited, requested=None (default path)",
       lambda: authorized_years({"chronology": {"train": [2029, 2032], "dev": [2031], "prohibited": [2032]}}, "train", None),
       expect_reject=True)
# adjacent: malformed chronology
attack("plan.chronology.train malformed ['x']",
       lambda: authorized_years({"chronology": {"train": ["x"], "dev": [], "prohibited": []}}, "train", None))
attack("plan.chronology missing entirely, requested=[2029]",
       lambda: authorized_years({}, "train", [2029]))
attack("plan.chronology missing entirely, requested=None",
       lambda: authorized_years({}, "train", None), expect_reject=False)

print(json.dumps(results, indent=1))
bypassed = [r for r in results if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")]
print("\nBYPASSED/UNEXPECTED:", json.dumps(bypassed, indent=1))
