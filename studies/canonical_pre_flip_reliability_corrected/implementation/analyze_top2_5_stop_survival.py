from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
STUDY = Path(__file__).resolve().parents[1]
RESULTS = STUDY / "results"
KEY = ["regime_start_ns", "observation_time"]
STOP_ATR = (0.50, 0.75, 1.00, 1.25, 1.50, 2.00)
NQ_DOLLARS_PER_POINT = 20.0


def assert_keys(df: pd.DataFrame, name: str) -> None:
    if df[KEY].isna().any().any() or df.duplicated(KEY).any():
        raise RuntimeError(f"{name}: duplicate or null checkpoint key")


def load_flip_times(direction: str) -> pd.DataFrame:
    frames = []
    for year in (2024, 2025):
        if direction == "bullish_fade":
            path = ROOT / f"studies/short_rth_pure_flip_prediction_enriched/_work/prepared_{year}.parquet"
        else:
            path = ROOT / f"studies/long_rth_mirrored_surface_top100_training/_work/attached_long_{year}.parquet"
        d = pd.read_parquet(path, columns=KEY + ["confirm_flip_ns"])
        assert_keys(d, f"{direction} {year}")
        frames.append(d)
    out = pd.concat(frames, ignore_index=True)
    assert_keys(out, direction)
    out["seconds_to_flip"] = (out.confirm_flip_ns - out.observation_time) / 1e9
    if not (out.seconds_to_flip > 0).all():
        raise RuntimeError(f"{direction}: non-positive confirmed-flip horizon")
    return out[KEY + ["seconds_to_flip"]]


def metric_rows(direction: str, cohort: str, d: pd.DataFrame) -> list[dict]:
    quantiles = (("p50", .50), ("p75", .75), ("p90", .90), ("p95", .95), ("p99", .99))
    rows = []
    for unit, column, multiplier in (
        ("ATR", "countertrend_mae_atr", 1.0),
        ("points", "countertrend_mae_points", 1.0),
        ("NQ_dollars_per_contract", "countertrend_mae_points", NQ_DOLLARS_PER_POINT),
    ):
        values = d[column].to_numpy(dtype=float) * multiplier
        row = {"direction": direction, "cohort": cohort, "unit": unit, "qualifying_flips": len(d)}
        row.update({name: float(np.quantile(values, q)) for name, q in quantiles})
        row["maximum"] = float(np.max(values))
        rows.append(row)
    return rows


def survival_rows(direction: str, cohort: str, d: pd.DataFrame) -> list[dict]:
    mae = d.countertrend_mae_atr.to_numpy(dtype=float)
    return [{"direction": direction, "cohort": cohort, "qualifying_flips": len(d),
             "stop_atr": stop, "surviving_flips": int((mae <= stop).sum()),
             "survival_to_confirmed_flip": float((mae <= stop).mean())}
            for stop in STOP_ATR]


def table_markdown(df: pd.DataFrame, cohort: str) -> str:
    part = df[df.cohort == cohort].copy()
    return part[["direction", "unit", "qualifying_flips", "p50", "p75", "p90", "p95", "p99", "maximum"]].to_markdown(index=False)


def survival_markdown(df: pd.DataFrame, cohort: str) -> str:
    part = df[df.cohort == cohort].copy()
    pivot = part.pivot(index="stop_atr", columns="direction", values="survival_to_confirmed_flip").reset_index()
    for c in ("bullish_fade", "bearish_fade"):
        pivot[c] = pivot[c].map(lambda x: f"{x:.1%}")
    return pivot.to_markdown(index=False)


def main() -> None:
    economic = pd.read_parquet(RESULTS / "economic_events.parquet")
    economic = economic[economic.top_pct == 2.5].copy()
    if economic.empty or economic.duplicated(["direction"] + KEY).any():
        raise RuntimeError("Top-2.5 economic population missing or duplicated")
    expected_directions = {"bullish_fade", "bearish_fade"}
    if set(economic.direction.unique()) != expected_directions:
        raise RuntimeError("Top-2.5 economic population has unexpected/missing directions")
    thresholds = pd.read_csv(STUDY / "threshold_summary.csv")
    expected_counts = thresholds[thresholds.top_pct == 2.5].set_index("direction").signals.astype(int).to_dict()
    actual_counts = economic.groupby("direction").size().to_dict()
    if expected_counts != actual_counts:
        raise RuntimeError(f"Top-2.5 economic/threshold count mismatch: {actual_counts} vs {expected_counts}")

    metric_out, survival_out = [], []
    for direction in ("bullish_fade", "bearish_fade"):
        e = economic[economic.direction == direction].copy()
        flips = load_flip_times(direction)
        joined = e.merge(flips, on=KEY, how="left", validate="one_to_one")
        if len(joined) != len(e) or joined.seconds_to_flip.isna().any():
            raise RuntimeError(f"{direction}: incomplete pure-flip timestamp join")
        cohorts = {
            "flip_le_300": joined[joined.seconds_to_flip <= 300.0],
            "flip_le_600": joined[joined.seconds_to_flip <= 600.0],
            "eventual_flip": joined,
        }
        for cohort, d in cohorts.items():
            if d.empty: raise RuntimeError(f"{direction} {cohort}: no qualifying flips")
            metric_out.extend(metric_rows(direction, cohort, d))
            survival_out.extend(survival_rows(direction, cohort, d))

    metrics = pd.DataFrame(metric_out)
    survival = pd.DataFrame(survival_out)
    metrics.to_csv(RESULTS / "top2_5_flip_mae_statistics.csv", index=False)
    survival.to_csv(RESULTS / "top2_5_flip_stop_survival.csv", index=False)

    report = """# Top 2.5% First-Signal MAE and Stop Survival

All cohorts use pure `confirm_flip_ns` timing. The primary table excludes every
signal whose confirmed flip occurs after 300 seconds. The 600-second and
eventual tables are cumulative secondary cohorts, not disjoint buckets.

`NQ dollars per contract = MAE points × $20`. Stop survival is descriptive and
uses exactly `countertrend_mae_atr <= stop_atr`; it does not simulate an order,
fill, slippage, or commission.

This is an event-corrected artifact comparison. Bullish selection comes from
the provisional artifact with inherited one-second feature look-ahead; Bearish
selection is strict-causal. Directional differences cannot establish structural
market asymmetry.

## Primary — confirmed flip within 300 seconds

""" + table_markdown(metrics, "flip_le_300") + """

### Fixed-stop survival

""" + survival_markdown(survival, "flip_le_300") + """

## Secondary — confirmed flip within 600 seconds

""" + table_markdown(metrics, "flip_le_600") + """

### Fixed-stop survival

""" + survival_markdown(survival, "flip_le_600") + """

## Secondary — eventual confirmed flips

""" + table_markdown(metrics, "eventual_flip") + """

### Fixed-stop survival

""" + survival_markdown(survival, "eventual_flip") + "\n"
    (STUDY / "top2_5_flip_stop_survival_report.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
