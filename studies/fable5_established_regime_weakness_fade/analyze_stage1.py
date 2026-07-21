"""Stage-1 cohort summaries and predeclared divergence gate."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import COHORTS, RESULTS, STAGE1_GATE

METRICS = RESULTS / "stage1_regime_metrics.parquet"


def cohort_masks(d: pd.DataFrame) -> dict[str, pd.Series]:
    p = d["final_flip_pnl_atr"]
    m = d["peak_mfe_atr"]
    return {
        "all_regimes": pd.Series(True, index=d.index),
        "flip_pnl_ge_0p5": p >= 0.5,
        "flip_pnl_ge_1p0": p >= 1.0,
        "flip_pnl_lt_0": p < 0,
        "flip_pnl_0_to_0p5": (p >= 0) & (p < 0.5),
        "mfe_ge_1_flip_lt_0p5": (m >= 1.0) & (p < 0.5),
        "mfe_ge_1_flip_ge_0p5": (m >= 1.0) & (p >= 0.5),
        "mfe_lt_1": m < 1.0,
    }


MEDIAN_COLS = [
    "duration_s", "final_flip_pnl_atr", "peak_mfe_atr", "time_to_0p5_s",
    "time_to_1p0_s", "time_peak_to_flip_s", "giveback_atr",
    "retained_qual", "retained_peak", "retained_m60", "retained_m30",
    "retained_flip", "new_progress_windows", "w4_qual", "w4_peak",
    "w4_m60", "w4_m30", "w4_flip",
]


def summarize(d: pd.DataFrame, split: str, split_value: str) -> pd.DataFrame:
    rows = []
    n_pop = len(d)
    for cohort, mask in cohort_masks(d).items():
        x = d[mask]
        row = {
            "split": split,
            "split_value": split_value,
            "cohort": cohort,
            "cohort_label": COHORTS[cohort],
            "count": len(x),
            "pct_population": len(x) / n_pop if n_pop else np.nan,
        }
        row.update({f"median_{c}": x[c].median() for c in MEDIAN_COLS})
        for c in ("w4_qual", "w4_peak", "w4_m60", "w4_m30", "w4_flip"):
            row[f"availability_{c}"] = x[c].notna().mean() if len(x) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate_gate(d: pd.DataFrame, period: str) -> dict:
    x = d[d["period"] == period]
    masks = cohort_masks(x)
    win = x[masks["mfe_ge_1_flip_ge_0p5"]]
    fail = x[masks["mfe_ge_1_flip_lt_0p5"]]
    paired_w4_rise = (win["w4_flip"] - win["w4_m60"]).dropna()

    def ratio(a: pd.Series, b: pd.Series) -> float:
        den = float(b.median())
        return float(a.median() / den) if den != 0 else np.nan

    vals = {
        "period": period,
        "winner_count": len(win),
        "failed_runner_count": len(fail),
        "duration_ratio": ratio(win["duration_s"], fail["duration_s"]),
        "peak_mfe_ratio": ratio(win["peak_mfe_atr"], fail["peak_mfe_atr"]),
        "progress_windows_delta": float(win["new_progress_windows"].median() - fail["new_progress_windows"].median()),
        "retained_m60_delta": float(win["retained_m60"].median() - fail["retained_m60"].median()),
        "winner_w4_rise_m60_to_flip": float(paired_w4_rise.median()),
        "winner_w4_rise_paired_n": int(len(paired_w4_rise)),
        "winner_w4_rise_paired_fraction": float(len(paired_w4_rise) / len(win)) if len(win) else 0.0,
        "winner_peak_to_flip_s": float(win["time_peak_to_flip_s"].median()),
        "winner_giveback_atr": float(win["giveback_atr"].median()),
    }
    structural = {
        "duration": vals["duration_ratio"] >= STAGE1_GATE["duration_ratio_min"],
        "peak_mfe": vals["peak_mfe_ratio"] >= STAGE1_GATE["peak_mfe_ratio_min"],
        "progress_windows": vals["progress_windows_delta"] >= STAGE1_GATE["progress_windows_delta_min"],
        "retention_m60": vals["retained_m60_delta"] >= STAGE1_GATE["retained_m60_delta_min"],
    }
    minimum_n = STAGE1_GATE[
        "minimum_winner_count_train" if period == "train" else "minimum_winner_count_2025"
    ]
    minimum_paired_n = STAGE1_GATE[
        "minimum_paired_w4_count_train" if period == "train" else "minimum_paired_w4_count_2025"
    ]
    vals["structural_conditions"] = structural
    vals["structural_pass_count"] = int(sum(structural.values()))
    vals["sample_pass"] = len(win) >= minimum_n
    vals["weakness_window_pass"] = bool(
        vals["winner_w4_rise_paired_n"] >= minimum_paired_n
        and vals["winner_w4_rise_m60_to_flip"] >= STAGE1_GATE["weakness_rise_min"]
        and vals["winner_peak_to_flip_s"] >= STAGE1_GATE["minimum_median_peak_to_flip_s"]
        and vals["winner_giveback_atr"] >= STAGE1_GATE["minimum_median_giveback_atr"]
    )
    vals["pass"] = bool(
        vals["sample_pass"]
        and vals["structural_pass_count"] >= STAGE1_GATE["minimum_structural_conditions"]
        and vals["weakness_window_pass"]
    )
    return vals


def build_report(summary: pd.DataFrame, gate_train: dict, gate_val: dict) -> str:
    key = summary[(summary["split"] == "period")
                  & (summary["split_value"].isin(["train", "validation"]))
                  & (summary["cohort"].isin([
                      "all_regimes", "mfe_ge_1_flip_lt_0p5",
                      "mfe_ge_1_flip_ge_0p5", "mfe_lt_1"
                  ]))].copy()
    cols = ["split_value", "cohort_label", "count", "pct_population",
            "median_duration_s", "median_final_flip_pnl_atr",
            "median_peak_mfe_atr", "median_new_progress_windows",
            "median_retained_m60", "median_giveback_atr",
            "median_w4_m60", "median_w4_m30", "median_w4_flip"]
    table = key[cols].to_markdown(index=False, floatfmt=".3f")
    decision = (
        "ESTABLISHED_REGIME_FILTER_FOUND"
        if gate_train["pass"] and gate_val["pass"]
        else "NO_CLEAR_ESTABLISHED_REGIME_FILTER"
    )
    return f"""# Established Regime Weakness Fade — Stage 1

## Decision

`{decision}`

Stage 2 is {'authorized by the predeclared gate' if decision.startswith('ESTABLISHED') else 'not run because the predeclared divergence gate did not pass'}.

## Key cohort contrast

{table}

## Gate — 2021–2024 discovery

```json
{json.dumps(gate_train, indent=2)}
```

## Gate — 2025 sanity check

```json
{json.dumps(gate_val, indent=2)}
```

## Interpretation limits

- Cohorts use final flip PnL and peak MFE only as retrospective descriptive labels; they are not live filters.
- W4 values are attached from the last checkpoint whose availability time is at or before each target (observation T plus one second).
- W4 was fit on 2021–2024, so discovery-period W4 contrasts are in-sample. The 2025 gate is the out-of-sample sanity check.
- W4 coverage ends at regime age 1,800 seconds. A score is considered "at" a target only when its availability is within one native checkpoint interval (30 seconds in 2021–2024; 5 seconds in 2025), so stale capped scores are reported unavailable.
- No 2026 row is scored, characterized, or summarized in Stage 1. The untouched test remains sealed unless Stage 2 is fully specified and frozen.
"""


def main() -> None:
    d = pd.read_parquet(METRICS)
    assert int(d["year"].max()) <= 2025, "2026 metric row exposed before freeze"
    assert not (d["period"] == "test").any(), "test period exposed before freeze"
    frames = []
    for period, x in d.groupby("period", sort=False):
        frames.append(summarize(x, "period", period))
    train = d[d["period"] == "train"]
    for direction, x in train.groupby("direction"):
        frames.append(summarize(x, "direction", "long" if direction == 1 else "short"))
    for session, x in train.groupby("session"):
        frames.append(summarize(x, "session", session))
    out = pd.concat(frames, ignore_index=True)
    out.to_parquet(RESULTS / "stage1_cohort_summary.parquet", index=False)
    gate_train = evaluate_gate(d, "train")
    gate_val = evaluate_gate(d, "validation")
    gate = {
        "predeclared_thresholds": STAGE1_GATE,
        "train": gate_train,
        "validation": gate_val,
        "decision": (
            "ESTABLISHED_REGIME_FILTER_FOUND"
            if gate_train["pass"] and gate_val["pass"]
            else "NO_CLEAR_ESTABLISHED_REGIME_FILTER"
        ),
    }
    (RESULTS / "stage1_gate.json").write_text(
        json.dumps(gate, indent=2), encoding="utf-8"
    )
    (RESULTS / "stage1_report.md").write_text(
        build_report(out, gate_train, gate_val), encoding="utf-8"
    )
    print(gate["decision"])


if __name__ == "__main__":
    main()
