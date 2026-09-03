"""A1b: does the compiled-plan + lifecycle wiring reject role expansion at the stage entry points?"""
from __future__ import annotations
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import build_study, lifecycle, ROOT  # noqa

res = []
with tempfile.TemporaryDirectory() as td:
    study = build_study(Path(td))
    lc = lifecycle(study, execute=True)
    print("compile:", lc.compile()["status"])
    print("prepare:", lc.prepare()["status"])
    plan = json.loads((study / "compiled_plan.json").read_text())
    print("plan chronology:", plan["chronology"])
    auth = json.loads((study / "artifacts" / "experiment_authorization.json").read_text())
    print("authorization:", {k: auth[k] for k in ("train_years", "oos_years", "prohibited_years")})

    def t(name, fn, expect_reject=True):
        try:
            out = fn()
            res.append({"case": name, "outcome": f"RETURNED {out!r}"[:200], "verdict": "BYPASSED" if expect_reject else "OK"})
        except Exception as exc:
            res.append({"case": name, "outcome": f"{type(exc).__name__}: {str(exc)[:200]}",
                        "verdict": "BLOCKED" if expect_reject else "UNEXPECTED_REJECT"})

    t("_authorized_years(train,[2031]) via real auth artifact", lambda: lc._authorized_years(plan, "train", [2031]))
    t("_authorized_years(oos,[2030])", lambda: lc._authorized_years(plan, "oos", [2030]))
    t("_authorized_years(train,[2032]) prohibited", lambda: lc._authorized_years(plan, "train", [2032]))
    t("_authorized_years(train,[]) empty", lambda: lc._authorized_years(plan, "train", []))
    t("_authorized_years(train,None) legal", lambda: lc._authorized_years(plan, "train", None), expect_reject=False)
    t("_authorized_years(oos,None) legal", lambda: lc._authorized_years(plan, "oos", None), expect_reject=False)
    # Tamper the authorization artifact to add a prohibited year to train
    ap = study / "artifacts" / "experiment_authorization.json"
    orig = ap.read_text()
    a2 = json.loads(orig); a2["train_years"] = [2029, 2030, 2032]
    ap.write_text(json.dumps(a2))
    t("tampered auth artifact adds 2032 to train_years", lambda: lc._authorized_years(plan, "train", [2032]))
    t("tampered auth artifact, requested=None", lambda: lc._authorized_years(plan, "train", None))
    ap.write_text(orig)
    # Delete the authorization artifact entirely -> does it fail open?
    ap.unlink()
    t("authorization artifact DELETED, requested=[2031] on train", lambda: lc._authorized_years(plan, "train", [2031]))
    t("authorization artifact DELETED, requested=None on train", lambda: lc._authorized_years(plan, "train", None), expect_reject=False)
    ap.write_text(orig)
    # Stage entry points with options.years pointing at the wrong role
    from research_workflow.lifecycle_v2 import V2Options
    lc.opts.years = [2031]
    t("collection() with opts.years=[2031] (dev year in train stage)", lambda: lc.collection())
    lc.opts.years = [2032]
    t("collection() with opts.years=[2032] (prohibited)", lambda: lc.collection())
    lc.opts.years = [2029]
    t("oos() with opts.years=[2029] (train year in oos stage)", lambda: lc.oos())
    lc.opts.years = None

print(json.dumps(res, indent=1))
print("\nBYPASSED:", json.dumps([r for r in res if r["verdict"] in ("BYPASSED", "UNEXPECTED_REJECT")], indent=1))
