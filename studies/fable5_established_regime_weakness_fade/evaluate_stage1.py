"""Stage-1 cohort summary + predeclared gate evaluation.

The gate (common.STAGE1_GATE, frozen in SPEC.md before any Stage-1 result
was generated) is applied mechanically to the 7-vs-6 contrast on BOTH
chronological splits (train 2021-2024, validation 2025). Emits
ESTABLISHED_REGIME_FILTER_FOUND or NO_CLEAR_ESTABLISHED_REGIME_FILTER.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import AUDIT, RESULTS, STAGE1_GATE

METRICS_PATH = RESULTS / "stage1_regime_metrics.parquet"

COHORT_MASKS = {
    "1_all": lambda m: np.ones(len(m), dtype=bool),
    "2_flip_ge_0p5": lambda m: m["final_flip_pnl_atr"] >= 0.5,
    "3_flip_ge_1p0": lambda m: m["final_flip_pnl_atr"] >= 1.0,
    "4_flip_lt_0": lambda m: m["final_flip_pnl_atr"] < 0,
    "5_flip_0_to_0p5": lambda m: (m["final_flip_pnl_atr"] >= 0)
                                 & (m["final_flip_pnl_atr"] < 0.5),
    "6_mfe1_flip_lt_0p5": lambda m: (m["peak_mfe_atr"] >= 1.0)
                                    & (m["final_flip_pnl_atr"] < 0.5),
    "7_WINNERS": lambda m: (m["peak_mfe_atr"] >= 1.0)
                           & (m["final_flip_pnl_atr"] >= 0.5),
    "8_never_mfe1": lambda m: m["peak_mfe_atr"] < 1.0,
}

MED_COLS = ["duration_s", "final_flip_pnl_atr", "peak_mfe_atr",
            "time_to_0p5_s", "time_to_1p0_s", "time_peak_to_flip_s",
            "giveback_atr", "retained_qual", "retained_flip", "retained_m60", "retained_m30",
            "retained_peak", "new_progress_windows",
            "w4_qual", "w4_peak", "w4_m60", "w4_m30", "w4_flip"]


def summarize(m: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for name, fn in COHORT_MASKS.items():
        g = m[fn(m)]
        row = {"split": label, "cohort": name, "n": len(g),
               "pct": len(g) / len(m) if len(m) else np.nan}
        for c in MED_COLS:
            row[f"med_{c}"] = float(g[c].median()) if len(g) else np.nan
        both = g[["w4_m60", "w4_flip"]].dropna()
        row["n_paired_w4"] = len(both)
        row["med_w4_rise_m60_to_flip"] = (
            float((both["w4_flip"] - both["w4_m60"]).median())
            if len(both) else np.nan)
        row["w4_flip_availability"] = (float(g["w4_flip"].notna().mean())
                                       if len(g) else np.nan)
        rows.append(row)
    return pd.DataFrame(rows)


def gate_for_split(s: pd.DataFrame, split: str, min_winners: int,
                   min_paired: int) -> dict:
    g = STAGE1_GATE
    c7 = s[s["cohort"] == "7_WINNERS"].iloc[0]
    c6 = s[s["cohort"] == "6_mfe1_flip_lt_0p5"].iloc[0]
    conds = {
        "duration_ratio": (c7["med_duration_s"] / c6["med_duration_s"]
                           >= g["duration_ratio_min"]),
        "peak_mfe_ratio": (c7["med_peak_mfe_atr"] / c6["med_peak_mfe_atr"]
                           >= g["peak_mfe_ratio_min"]),
        "progress_windows_delta": (c7["med_new_progress_windows"]
                                   - c6["med_new_progress_windows"]
                                   >= g["progress_windows_delta_min"]),
        "retained_m60_delta": (c7["med_retained_m60"] - c6["med_retained_m60"]
                               >= g["retained_m60_delta_min"]),
    }
    n_structural = int(sum(bool(v) for v in conds.values()))
    checks = {
        "split": split,
        **{f"cond_{k}": bool(v) for k, v in conds.items()},
        "n_structural_passed": n_structural,
        "structural_ok": n_structural >= g["minimum_structural_conditions"],
        "winner_count_ok": bool(c7["n"] >= min_winners),
        "paired_w4_ok": bool(c7["n_paired_w4"] >= min_paired),
        "w4_rise_ok": bool(np.isfinite(c7["med_w4_rise_m60_to_flip"])
                           and c7["med_w4_rise_m60_to_flip"]
                           >= g["weakness_rise_min"]),
        "peak_to_flip_ok": bool(c7["med_time_peak_to_flip_s"]
                                >= g["minimum_median_peak_to_flip_s"]),
        "giveback_ok": bool(c7["med_giveback_atr"]
                            >= g["minimum_median_giveback_atr"]),
        "winner_n": int(c7["n"]),
        "paired_w4_n": int(c7["n_paired_w4"]),
        "duration_ratio_val": float(c7["med_duration_s"] / c6["med_duration_s"]),
        "peak_mfe_ratio_val": float(c7["med_peak_mfe_atr"]
                                    / c6["med_peak_mfe_atr"]),
        "progress_windows_delta_val": float(c7["med_new_progress_windows"]
                                            - c6["med_new_progress_windows"]),
        "retained_m60_delta_val": float(c7["med_retained_m60"]
                                        - c6["med_retained_m60"]),
        "w4_rise_val": float(c7["med_w4_rise_m60_to_flip"]),
    }
    checks["pass"] = bool(
        checks["structural_ok"] and checks["winner_count_ok"]
        and checks["paired_w4_ok"] and checks["w4_rise_ok"]
        and checks["peak_to_flip_ok"] and checks["giveback_ok"])
    return checks


def main() -> None:
    m = pd.read_parquet(METRICS_PATH)
    assert int(m["year"].max()) <= 2025

    train = m[m["period"] == "train"]
    val = m[m["period"] == "validation"]

    parts = [summarize(train, "train"), summarize(val, "validation")]
    for d in (1, -1):
        parts.append(summarize(train[train["direction"] == d],
                               f"train_{'long' if d == 1 else 'short'}"))
    for s in ("RTH", "ETH"):
        parts.append(summarize(train[train["session"] == s], f"train_{s}"))
    summary = pd.concat(parts, ignore_index=True)
    # Independent evaluator: never overwrite the canonical artifact produced
    # by analyze_stage1.py. This copy exists only for completion-audit parity.
    summary.to_parquet(AUDIT / "stage1_cohort_summary_independent.parquet", index=False)

    g_tr = gate_for_split(parts[0], "train",
                          STAGE1_GATE["minimum_winner_count_train"],
                          STAGE1_GATE["minimum_paired_w4_count_train"])
    g_vl = gate_for_split(parts[1], "validation",
                          STAGE1_GATE["minimum_winner_count_2025"],
                          STAGE1_GATE["minimum_paired_w4_count_2025"])
    decision = ("ESTABLISHED_REGIME_FILTER_FOUND"
                if g_tr["pass"] and g_vl["pass"]
                else "NO_CLEAR_ESTABLISHED_REGIME_FILTER")

    (AUDIT / "stage1_gate_evaluation.json").write_text(
        json.dumps({"gate": STAGE1_GATE, "train": g_tr, "validation": g_vl,
                    "decision": decision}, indent=2), encoding="utf-8")

    # compact human-readable summary
    lines = [f"# Stage 1 summary — decision: {decision}\n"]
    for label, part in [("train 2021-2024", parts[0]),
                        ("validation 2025", parts[1])]:
        lines.append(f"\n## {label}\n")
        show = part.set_index("cohort")[
            ["n", "pct", "med_duration_s", "med_final_flip_pnl_atr",
             "med_peak_mfe_atr", "med_time_to_1p0_s",
             "med_time_peak_to_flip_s", "med_giveback_atr",
             "med_retained_qual", "med_retained_m60", "med_new_progress_windows", "med_w4_m60",
             "med_w4_flip", "med_w4_rise_m60_to_flip", "n_paired_w4",
             "w4_flip_availability"]]
        lines.append(show.round(3).T.to_markdown())
    lines.append("\n\n## Gate evaluation\n")
    lines.append(pd.DataFrame([g_tr, g_vl]).T.to_markdown())
    (RESULTS / "stage1_summary.md").write_text("\n".join(lines),
                                               encoding="utf-8")

    with pd.option_context("display.width", 250, "display.max_columns", 40):
        print(pd.DataFrame([g_tr, g_vl]).T.to_string())
    print(f"\nDECISION: {decision}")


if __name__ == "__main__":
    main()
