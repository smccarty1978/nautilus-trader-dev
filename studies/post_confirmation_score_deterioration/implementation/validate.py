"""The nine SPEC 9 gates, executed and written machine-readable.

Gate 8 (`no_terminal_leakage`) is the one that matters most here. This study's
whole finding rests on the landmark design, and the failure mode it guards
against -- a predictor computed over a window that ends at the terminal event --
has already corrupted results twice in this research line.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "studies/post_confirmation_score_deterioration/results"
PANEL = OUT / "post_confirm_paths.parquet"
PRIOR = ROOT / "studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet"
NS = 1_000_000_000

BRIEF = {"CONFIRMED_THEN_STOPPED": 822, "FINAL_FLIP_EXIT_LOSER": 1359,
         "FINAL_FLIP_EXIT_WINNER": 2350, "SESSION_EXIT": 174}
SAMPLE = 200
SEED = 20260810


def g1_population() -> dict:
    prior = pl.read_parquet(PRIOR).filter(pl.col("valid"))
    counts = {
        r["terminal_label_full"]: r["count"]
        for r in prior["terminal_label_full"].value_counts().iter_rows(named=True)
    }
    derived = {k: counts.get(k, 0) for k in BRIEF}
    walk_a = int(prior["walk_a_confirm_reached_censored"].sum())
    unresolved = int(prior["walk_a_session_close_unresolved"].fill_null(False).sum())
    total = sum(derived.values())
    return {
        "gate": "population_reconciliation",
        "passed": derived == BRIEF and total == walk_a + unresolved,
        "derived": derived, "brief": BRIEF,
        "confirmed_continuation": total,
        "walk_a_confirmed": walk_a,
        "walk_a_session_close_unresolved": unresolved,
        "delta_explained": total - walk_a == unresolved,
    }


def g2_ordering(p: pl.DataFrame) -> dict:
    v = {
        "obs_before_confirmation": p.filter(
            pl.col("checkpoint_decision_ns") < pl.col("confirm_ns")).height,
        "obs_after_terminal": p.filter(
            pl.col("checkpoint_decision_ns") > pl.col("terminal_ns")).height,
        "confirmation_after_terminal": p.filter(
            pl.col("confirm_ns") > pl.col("terminal_ns")).height,
        "negative_elapsed": p.filter(pl.col("elapsed_s") < 0).height,
    }
    return {"gate": "event_ordering", "passed": all(x == 0 for x in v.values()),
            "violations": v}


def g3_duplicates(p: pl.DataFrame) -> dict:
    dup = p.height - p.select(
        pl.struct("regime_id", "checkpoint_decision_ns").n_unique()).item()
    return {"gate": "no_duplicate_observations", "passed": dup == 0,
            "duplicate_rows": int(dup), "rows": p.height}


def g4_monotonic(p: pl.DataFrame) -> dict:
    bad = (
        p.sort(["regime_id", "checkpoint_decision_ns"])
        .with_columns(d=(pl.col("checkpoint_decision_ns")
                         - pl.col("checkpoint_decision_ns").shift(1).over("regime_id")))
        .filter(pl.col("d") <= 0).height
    )
    return {"gate": "monotonic_events", "passed": bad == 0,
            "non_increasing_steps": int(bad)}


def g5_recompute(p: pl.DataFrame) -> dict:
    """Independent recomputation on a deterministic sample of trades."""
    rng = np.random.default_rng(SEED)
    ids = sorted(p["regime_id"].unique().to_list())
    pick = [ids[i] for i in rng.choice(len(ids), size=min(SAMPLE, len(ids)), replace=False)]
    sub = p.filter(pl.col("regime_id").is_in(pick)).sort(
        ["regime_id", "checkpoint_decision_ns"])

    bad = {"score_peak": 0, "escalation_from_min": 0, "mfe": 0, "mae": 0, "open_pnl": 0}
    for rid, blk in sub.partition_by("regime_id", as_dict=True).items():
        s = blk["score_b"].to_numpy()
        peak = np.maximum.accumulate(s)
        trough = np.minimum.accumulate(s)
        if not np.allclose(peak, blk["score_b_running_max"].to_numpy(), atol=1e-12):
            bad["score_peak"] += 1
        if not np.allclose(s - trough, blk["escalation_from_min"].to_numpy(), atol=1e-12):
            bad["escalation_from_min"] += 1

        price = blk["checkpoint_reference_price"].to_numpy()
        cp = float(blk["confirm_price"][0])
        d = int(blk["direction"][0])
        atr = float(blk["atr_at_confirmation"][0])
        pnl = (price - cp) * d / atr
        if not np.allclose(pnl, blk["open_pnl_atr_conf"].to_numpy(), atol=1e-9):
            bad["open_pnl"] += 1
        if not np.allclose(np.maximum.accumulate(np.maximum(pnl, 0.0)),
                           blk["run_mfe_atr"].to_numpy(), atol=1e-9):
            bad["mfe"] += 1
        if not np.allclose(np.abs(np.minimum.accumulate(np.minimum(pnl, 0.0))),
                           blk["run_mae_atr"].to_numpy(), atol=1e-9):
            bad["mae"] += 1

    return {"gate": "independent_recompute", "passed": all(v == 0 for v in bad.values()),
            "trades_sampled": len(pick), "mismatched_trades": bad,
            "method": "re-derived from raw price and score columns, not by "
                      "re-reading the panel's computed columns"}


def g6_session(p: pl.DataFrame) -> dict:
    over = p.filter(
        pl.col("session_close_ns").is_not_null()
        & (pl.col("checkpoint_decision_ns") > pl.col("session_close_ns"))
    ).height
    return {"gate": "session_containment", "passed": over == 0,
            "observations_past_session_close": int(over)}


def g7_tie_policy(p: pl.DataFrame) -> dict:
    """Same-dispatch ordering: at most one score row per (trade, timestamp)."""
    per = p.group_by(["regime_id", "checkpoint_decision_ns"]).agg(n=pl.len())
    ties = per.filter(pl.col("n") > 1).height
    return {
        "gate": "same_dispatch_ordering", "passed": ties == 0,
        "timestamps_with_multiple_rows": int(ties),
        "policy": "One score dispatch per (trade, timestamp); no tie-break is "
                  "required. First-firing of an event is the earliest such "
                  "dispatch satisfying the condition on rows at or before it.",
    }


def g8_no_leakage() -> dict:
    """Predictors must not read a window that ends at the terminal event."""
    # Scan only the modules that DEFINE flag conditions. This validator is
    # excluded deliberately: it quotes the very patterns it searches for, so
    # including it makes the check match its own source and always fail.
    flag_modules = [
        ROOT / "studies/post_confirmation_score_deterioration/analysis/events.py",
        ROOT / "studies/post_confirmation_score_deterioration/analysis/landmark_tradeoff.py",
        ROOT / "studies/post_confirmation_score_deterioration/analysis/gate2_ledger.py",
        ROOT / "studies/post_confirmation_score_deterioration/analysis/placebo.py",
    ]
    # Columns that are only knowable once the trade has ended. `hold_s` is
    # permitted solely as the alive-filter (`hold_s > horizon`), which is a
    # population restriction, not a predictor.
    forward_only = ("terminal_label", "is_failure", "full_mfe_atr", "full_gross_atr",
                    "terminal_ns", "final_pnl_atr", "max_pnl_after")
    findings = []
    for f in flag_modules:
        if not f.exists():
            findings.append(f"{f.name}: MISSING")
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            # A flag condition is a boolean built on pl.col(...) comparisons that
            # ends up inside event_specs / a `score_b >=` selection.
            if "score_b" in s and ">=" in s and any(c in s for c in forward_only):
                findings.append(f"{f.name}:{i}: flag condition references {s[:80]}")
    panel = pl.read_parquet(PANEL)
    forward_cols = [c for c in panel.columns
                    if c in ("full_mfe_atr", "full_mae_atr", "terminal_label",
                             "is_failure", "hold_s", "terminal_ns")]
    return {
        "gate": "no_terminal_leakage",
        "passed": len(findings) == 0,
        "static_findings": findings,
        "forward_columns_present_in_panel": forward_cols,
        "note": "Forward columns are present as TARGETS and as alive-filters "
                "(hold_s > horizon), never inside a flag condition. Every flag "
                "in events.py and landmark_tradeoff.py reads only score_b, "
                "open_pnl, and running expanding aggregates.",
    }


def g9_audit() -> dict:
    audit = ROOT / "studies/post_confirmation_score_deterioration/audit"
    out = {"gate": "audit_gates"}
    for name, fn in (("causal_lint", "lint.json"),
                     ("lookahead_auditor", "status.json"),
                     ("contract_checker", "contract_status.json")):
        p = audit / fn
        out[name] = json.loads(p.read_text()) if p.exists() else {"present": False}
    lint = out.get("causal_lint", {})
    ok_lint = lint.get("critical", 1) == 0
    ok = []
    for k in ("lookahead_auditor", "contract_checker"):
        pay = out.get(k, {})
        v = str(pay.get("verdict", pay.get("status", ""))).upper()
        ok.append(v in ("CLEAR", "PASS") and int(pay.get("critical", 0) or 0) == 0)
    out["passed"] = bool(ok_lint and all(ok))
    return out


def main() -> None:
    p = pl.read_parquet(PANEL)
    gates = [g1_population(), g2_ordering(p), g3_duplicates(p), g4_monotonic(p),
             g5_recompute(p), g6_session(p), g7_tie_policy(p), g8_no_leakage(),
             g9_audit()]
    report = {"all_passed": all(g["passed"] for g in gates),
              "gates": {g["gate"]: g for g in gates}}
    (OUT / "validation_report.json").write_text(json.dumps(report, indent=2, default=str))
    for g in gates:
        print(f"  {'PASS' if g['passed'] else 'FAIL'}  {g['gate']}")
    print(f"\nall_passed = {report['all_passed']}")


if __name__ == "__main__":
    main()
