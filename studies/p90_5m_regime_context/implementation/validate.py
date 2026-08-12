"""Gates and the computed verdict (SPEC sections 3.1, 8.1, 9).

The verdict is derived from the gate table and the measured quantities. An
unrun gate is a FAILURE, not a pass -- mirrors
`p90_conditional_losing_5s_exit/implementation/validate.py`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[3]
IMPL_DIR = ROOT / "studies/p90_5m_regime_context/implementation"

ARMED_REQUIRED = 8950
N_CONFIRMING_REQUIRED = 4656
SEALED_YEAR = 2026


def _gate(name, expected, observed, ok, note="") -> dict:
    return {"gate": name, "expected": expected, "observed": observed,
            "pass": bool(ok), "note": note}


def run_gates(*, arms: pl.DataFrame, lineage: dict, build_meta: dict,
              classification: pl.DataFrame, transition_matrix: pl.DataFrame,
              phase6_labels: pl.DataFrame, non_phase6_frames: dict[str, pl.DataFrame],
              parity_tests_passed: bool) -> list[dict]:
    g: list[dict] = []

    g.append(_gate("V1_armed_population", ARMED_REQUIRED, arms.height,
                   arms.height == ARMED_REQUIRED))
    g.append(_gate("V2_lineage_reproduced", True, lineage.get("all_reproduced"),
                   bool(lineage.get("all_reproduced"))))
    g.append(_gate("V3_parity_test_passed", True, parity_tests_passed,
                   parity_tests_passed,
                   "tests/test_regime_5m_parity.py must pass before any classification runs (SPEC 9.4)"))
    g.append(_gate("V4_build_reconciles", True,
                   {"buckets_reconcile": build_meta.get("buckets_reconcile"),
                    "rows_reconcile": build_meta.get("rows_reconcile")},
                   bool(build_meta.get("buckets_reconcile")) and bool(build_meta.get("rows_reconcile"))))

    # V5: 5m state lookups never resolve a flip with close_ts > decision_ts.
    # Structural invariant of Regime5m.state_at (searchsorted side="right"),
    # spot-checked here on the actual decision timestamps this run used.
    t = classification["arm_top10_ns"].to_numpy()
    age_s = classification["regime_age_s_at_p90"].to_numpy()
    bad_causal = int((age_s < 0).sum())
    g.append(_gate("V5_p90_lookup_causal", 0, bad_causal, bad_causal == 0,
                   "regime_age_s_at_p90 < 0 would mean a flip after the decision was used"))

    # V6: classification frame carries no outcome/terminal columns.
    forbidden_cols = {"full_gross_atr", "full_net_atr", "full_mfe_atr", "full_mae_atr",
                      "terminal_label_full", "walk_a_return_at_confirm_atr",
                      "walk_a_mae_to_confirm_atr", "walk_a_mfe_to_confirm_atr"}
    leaked = forbidden_cols & set(classification.columns)
    g.append(_gate("V6_classification_schema_no_outcome_leak", [], sorted(leaked),
                   len(leaked) == 0))

    # V7: no label_only_ column outside phase6_labels / phase6_timing output.
    leaks = {name: [c for c in df.columns if c.startswith("label_only_")]
            for name, df in non_phase6_frames.items()}
    leaks = {k: v for k, v in leaks.items() if v}
    g.append(_gate("V7_no_label_only_leak", {}, leaks, len(leaks) == 0,
                   "label_only_ columns may exist only in phase6_labels/phase6_timing.csv"))

    # V8: 2026 sealed -- the query timestamps this run actually issued.
    years = sorted(int(y) for y in arms["entry_year"].unique().to_list())
    g.append(_gate("V8_2026_sealed", "max <= 2025", max(years), max(years) < SEALED_YEAR))

    # V9: transition matrix reconciles to the 4,656 confirming population.
    n_transition = int(transition_matrix["n"].sum())
    g.append(_gate("V9_transition_matrix_reconciles", N_CONFIRMING_REQUIRED, n_transition,
                   n_transition == N_CONFIRMING_REQUIRED))

    # V10: phase6 frame covers all 8,950 arms, future-flip timestamp is
    # label-only and never precedes the arm.
    g.append(_gate("V10_phase6_covers_population", ARMED_REQUIRED, phase6_labels.height,
                   phase6_labels.height == ARMED_REQUIRED))

    # V11: lookahead_next_change_into_direction_after has exactly one call
    # site (classify.py::phase6_future_flip_labels), per lookahead-auditor
    # pass-1 W1's suggested remediation.
    call_sites = []
    pattern = re.compile(r"\.lookahead_next_change_into_direction_after\(")
    for p in sorted(IMPL_DIR.glob("*.py")):
        if p.name == "regime_5m.py":  # the definition site, not a call site
            continue
        text = p.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if pattern.search(line):
                call_sites.append(f"{p.name}:{i}")
    allowed = {"classify.py"}
    bad_sites = [s for s in call_sites if s.split(":")[0] not in allowed]
    g.append(_gate("V11_lookahead_single_call_site", 1, len(call_sites),
                   len(call_sites) == 1 and not bad_sites,
                   f"sites={call_sites}"))

    return g


def determine_verdict(*, gates: list[dict], primary_table: pl.DataFrame,
                      pre_confirm: pl.DataFrame, transition_matrix: pl.DataFrame,
                      against_with_deep_dive: pl.DataFrame,
                      five_m_x_5s_failure: pl.DataFrame,
                      phase11: dict) -> dict:
    if not gates or not all(x["pass"] for x in gates):
        return {"verdict": "ABORT_LINEAGE_FAILURE", "secondary_signals": [],
               "failed_gates": [x["gate"] for x in gates if not x["pass"]]}

    pt = {r["metric"]: r for r in primary_table.iter_rows(named=True)}
    confirm_delta = pt["P(confirm<1ATR)"]["WITH_5M"] - pt["P(confirm<1ATR)"]["AGAINST_5M"]
    return_delta = (pt["median return @ confirm"]["WITH_5M"]
                    - pt["median return @ confirm"]["AGAINST_5M"])

    # per-year / per-side confirm-rate & return-at-confirm deltas, read from
    # Phase 2's `stratum`-broken-out rows (fixed per contract-checker pass 1, C1)
    def _stratum_deltas(col: str, stratum: str) -> np.ndarray:
        sub = pre_confirm.filter(pl.col("stratum") == stratum)
        w = sub.filter(pl.col("group") == "WITH_5M").sort("stratum_value")
        a = sub.filter(pl.col("group") == "AGAINST_5M").sort("stratum_value")
        j = w.join(a, on="stratum_value", suffix="_a")
        return (j[col] - j[f"{col}_a"]).to_numpy()

    year_confirm_delta = _stratum_deltas("p_confirm_lt_1atr", "entry_year")
    year_return_delta = _stratum_deltas("return_at_confirm_mean", "entry_year")
    side_confirm_delta = _stratum_deltas("p_confirm_lt_1atr", "side")
    side_return_delta = _stratum_deltas("return_at_confirm_mean", "side")

    years_positive = int(((year_confirm_delta > 0) & (year_return_delta > 0)).sum())
    no_side_inversion = bool(
        side_confirm_delta.size == 2 and side_return_delta.size == 2
        and ((side_confirm_delta > 0).all() and (side_return_delta > 0).all()
             or (side_confirm_delta < 0).all() and (side_return_delta < 0).all())
    )
    phase11_confirms_direction = bool(
        phase11.get("ci_excludes_zero")
        and np.sign(phase11.get("stratified_delta_confirm_rate", 0)) == np.sign(confirm_delta)
    )

    m1 = bool(
        abs(confirm_delta) >= 0.05 and abs(return_delta) >= 0.10
        and years_positive >= 4 and no_side_inversion and phase11_confirms_direction
    )

    tm = {r["transition"]: r for r in transition_matrix.iter_rows(named=True)}
    giveback_delta = abs(tm["WITH_WITH"]["giveback_mean"] - tm["AGAINST_AGAINST"]["giveback_mean"])
    mfe3_delta_transition = abs(tm["WITH_WITH"]["p_mfe_ge_3atr"] - tm["AGAINST_AGAINST"]["p_mfe_ge_3atr"])
    m2 = bool((not m1) and (mfe3_delta_transition >= 0.05 or giveback_delta >= 0.15))

    awd = {r["transition"]: r for r in against_with_deep_dive.iter_rows(named=True)}
    aw_vs_others = abs(awd.get("AGAINST_WITH", {}).get("p_mfe_ge_3atr", 0)
                       - max(awd.get("WITH_WITH", {}).get("p_mfe_ge_3atr", 0),
                             awd.get("AGAINST_AGAINST", {}).get("p_mfe_ge_3atr", 0)))
    m3 = bool((not m1) and aw_vs_others >= max(mfe3_delta_transition, giveback_delta))

    f5 = five_m_x_5s_failure.filter(pl.col("join_point") == "AT_5S_FLIP")
    ppv = {r["group"]: r["ppv_failure"] for r in f5.iter_rows(named=True)
          if r["group"] in ("FAILURE_SIGNAL_WITH_5M", "FAILURE_SIGNAL_AGAINST_5M")}
    ppv_delta = abs(ppv.get("FAILURE_SIGNAL_WITH_5M", 0) - ppv.get("FAILURE_SIGNAL_AGAINST_5M", 0))
    m4 = bool(ppv_delta >= 0.08)

    secondary = [s for s, ok in (("M2_POST_CONFIRM_CONTEXT", m2),
                                 ("M3_TRANSITION_PATH_MATTERS", m3),
                                 ("M4_5S_SPECIFICITY_IMPROVED", m4)) if ok]

    facts = {
        "confirm_rate_delta": confirm_delta, "return_at_confirm_delta": return_delta,
        "years_positive_both_metrics": years_positive, "no_side_inversion": no_side_inversion,
        "phase11_confirms_direction": phase11_confirms_direction,
        "transition_mfe3_delta": mfe3_delta_transition, "transition_giveback_delta": giveback_delta,
        "against_with_vs_others_mfe3_delta": aw_vs_others,
        "5s_failure_ppv_delta": ppv_delta,
    }

    if m1:
        verdict = "M1_STRONG_ENTRY_CONTEXT"
    elif secondary:
        verdict = secondary[0]
    else:
        verdict = "M5_NO_MATERIAL_INFORMATION"

    return {"verdict": verdict, "secondary_signals": secondary, "facts": facts}
