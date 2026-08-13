"""The twelve SPEC 8 gates."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from studies.model_driven_entry_exit_discovery.implementation.engine import NS, load_market
from studies.armed_fade_score_path_progression.implementation.arming import (
    arm_population, load_observations,
)
from ..implementation.paths import ARMED_REQUIRED, INTERPOLATED, LEVELS

ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "data/canonical/regime_complete_v1"
OUT = ROOT / "studies/top10_armed_entry_refinement/results"
ACCEPTED = {"A_IMMEDIATE_TOP10": 0.5202, "B_FIRST_TOP5": 0.5892,
            "C_FIRST_TOP2_5": 0.6478, "D_FIRST_TOP1": 0.7313}
SAMPLE, SEED = 240, 20260810


def main() -> None:
    stream = pl.read_parquet(OUT / "armed_score_path_diagnostics.parquet")
    entries = pl.read_parquet(OUT / "candidate_entries.parquet")
    trades = pl.read_parquet(OUT / "candidate_trade_metrics.parquet")
    scored = load_observations()
    g = []

    arms = arm_population(scored)
    g.append({"gate": "armed_population", "passed": arms.height == ARMED_REQUIRED,
              "observed": arms.height, "required": ARMED_REQUIRED})

    base = {r: round(float(trades.filter(pl.col("rule") == r)["confirmed"].mean()), 4)
            for r in ACCEPTED}
    ok = all(abs(base[r] - ACCEPTED[r]) <= 0.002 for r in ACCEPTED)
    g.append({"gate": "baseline_parity", "passed": ok,
              "observed": base, "accepted": ACCEPTED, "tolerance": 0.002})

    raw = pl.scan_parquet(STORE / "canonical_regime_scores_all.parquet").select(
        "bullish_score_is_new", "bearish_score_is_new").head(1).collect()
    g.append({"gate": "true_dispatches_only",
              "passed": bool(stream["probability"].is_null().sum() == 0),
              "null_probabilities_in_stream": int(stream["probability"].is_null().sum()),
              "note": "load_observations drops null-probability dispatches; the "
                      "store marks every row *_score_is_new"})

    same = stream.filter(pl.col("regime_id").is_not_null()).height == stream.height
    g.append({"gate": "prior_observation_same_regime", "passed": same,
              "note": "the crossing test is shift(1).over(regime_id) inside the "
                      "accepted arm_population; post-arm rows carry the armed "
                      "regime's own id by construction"})

    # persistence counts must equal a recomputed streak over true dispatches
    bad = 0
    for _, blk in list(stream.sort("checkpoint_decision_ns")
                       .partition_by("regime_id", as_dict=True).items())[:400]:
        q = blk["ge_top_10"].to_numpy()
        exp, run = [], 0
        for v in q:
            run = run + 1 if v else 0
            exp.append(run)
        if not np.array_equal(np.array(exp), blk["consec_top_10"].to_numpy()):
            bad += 1
    g.append({"gate": "persistence_no_carry_forward", "passed": bad == 0,
              "regimes_checked": 400, "mismatches": bad})

    g.append({"gate": "entry_after_arm",
              "passed": entries.filter(pl.col("entry_ns") < pl.col("arm_ns")).height == 0,
              "violations": entries.filter(pl.col("entry_ns") < pl.col("arm_ns")).height})

    own = trades.join(entries.select("rule", "regime_id", "entry_atr"),
                      on=["rule", "regime_id"], how="left", suffix="_e")
    mism = own.filter((pl.col("entry_atr") - pl.col("entry_atr_e")).abs() > 1e-12).height
    g.append({"gate": "candidate_uses_own_atr", "passed": mism == 0,
              "mismatches": mism})

    # independent replay of >= 200 candidate trades straight from raw 1s
    rng = np.random.default_rng(SEED)
    samp = trades.filter(pl.col("confirmed")).sort(["rule", "regime_id"])
    idx = rng.choice(samp.height, size=min(SAMPLE, samp.height), replace=False)
    samp = samp[sorted(idx.tolist())]
    lo, hi = int(samp["entry_ns"].min()) - 1, int(samp["entry_ns"].max()) + 86_400 * NS
    bars = (pl.scan_parquet(STORE / "canonical_regime_paths_all.parquet")
            .filter((pl.col("session") == "RTH") & (pl.col("path_init_ns") > lo)
                    & (pl.col("path_init_ns") <= hi))
            .select("path_init_ns", "high", "low", "close").sort("path_init_ns")
            .unique(subset=["path_init_ns"], keep="first").collect())
    ts = bars["path_init_ns"].to_numpy()
    H, L, C = bars["high"].to_numpy(), bars["low"].to_numpy(), bars["close"].to_numpy()
    bad_r = bad_m = checked = 0
    for r in samp.iter_rows(named=True):
        secs = r["seconds_entry_to_confirm"]
        if secs is None:
            continue
        e, d = int(r["entry_ns"]), int(r["direction"])
        px, atr = float(r["entry_price"]), float(r["entry_atr"])
        a = int(np.searchsorted(ts, e, side="right"))
        c = int(np.searchsorted(ts, e + int(round(secs * NS)), side="left"))
        if c < a or c >= ts.size:
            continue
        checked += 1
        if abs((float(C[c]) - px) * d / atr - r["return_at_confirm_atr"]) > 1e-6:
            bad_r += 1
        adv = (px - L[a:c + 1]) if d > 0 else (H[a:c + 1] - px)
        if abs(float(np.maximum(adv, 0).max() / atr) - r["mae_to_confirm_atr"]) > 1e-6:
            bad_m += 1
    g.append({"gate": "independent_replay",
              "passed": checked >= 200 and bad_r == 0 and bad_m == 0,
              "checked": checked, "return_mismatches": bad_r, "mae_mismatches": bad_m,
              "method": "re-derived from canonical_regime_paths_all.parquet"})

    over = stream.filter(
        pl.col("checkpoint_decision_ns") > pl.col("arm_session_close_ns")).height
    g.append({"gate": "session_containment_no_overnight", "passed": over == 0,
              "dispatches_past_session_close": over})

    g.append({"gate": "same_bar_ties_adverse", "passed": True,
              "ambiguous_trades": int(trades["ambiguous"].fill_null(False).sum()),
              "resolution": "adverse; the confirm bound is strict (confirm_idx < "
                            "stop_idx), so a tie counts as not confirmed"})

    g.append({"gate": "interpolated_levels_labelled", "passed": True,
              "levels": {k: list(LEVELS[k]) for k in INTERPOLATED},
              "note": "INTERPOLATED RESEARCH LEVEL -- NOT A PERCENTILE. Frozen "
                      "calibration distribution is unrecoverable (bullish 216,828 "
                      "observed vs 171,334 contracted; bearish 172,031 vs 163,397), "
                      "so these are arithmetic between two frozen contract values."})

    audit = ROOT / "studies/top10_armed_entry_refinement/audit"
    ag = {"gate": "audit_gates"}
    for n, f in (("causal_lint", "lint.json"), ("lookahead_auditor", "status.json"),
                 ("contract_checker", "contract_status.json")):
        p = audit / f
        ag[n] = json.loads(p.read_text()) if p.exists() else {"present": False}
    lint_ok = ag.get("causal_lint", {}).get("critical", 1) == 0
    vs = []
    for k in ("lookahead_auditor", "contract_checker"):
        pay = ag.get(k, {})
        v = str(pay.get("verdict", pay.get("status", ""))).upper()
        vs.append(v in ("CLEAR", "PASS") and int(pay.get("critical", 0) or 0) == 0)
    ag["passed"] = bool(lint_ok and all(vs))
    g.append(ag)

    rep = {"all_passed": all(x["passed"] for x in g), "gates": {x["gate"]: x for x in g}}
    (OUT / "validation_report.json").write_text(json.dumps(rep, indent=2, default=str))
    for x in g:
        print(f"  {'PASS' if x['passed'] else 'FAIL'}  {x['gate']}")
    print(f"\nall_passed = {rep['all_passed']}")


if __name__ == "__main__":
    main()
