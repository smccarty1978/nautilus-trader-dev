"""Pre-fix versus repaired excursion distributions and monotonicity audit."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from CODEX_5_X_common import (  # noqa: E402
    LEGACY_ATLAS, NS, RESULTS, write_json, year_atlas_path,
)

VARS = ("current_mfe", "current_mae", "running_mfe", "running_mae")


def legacy_year(year: int) -> pd.DataFrame:
    start = pd.Timestamp(f"{year}-01-01", tz="UTC").value
    end = pd.Timestamp(f"{year + 1}-01-01", tz="UTC").value
    d = pd.read_parquet(
        LEGACY_ATLAS,
        columns=["observation_time", "direction", "regime_age",
                 "current_mfe", "current_mae"],
        filters=[("observation_time", ">=", start),
                 ("observation_time", "<", end)],
    )
    d["regime_start_ns"] = (
        d["observation_time"].astype(np.int64)
        - np.rint(d["regime_age"]).astype(np.int64) * NS
    )
    d["running_mfe"] = d["current_mfe"]
    d["running_mae"] = d["current_mae"]
    return d


def summarize(d: pd.DataFrame, version: str, year: int) -> list[dict]:
    rows: list[dict] = []
    d = d.sort_values(["regime_start_ns", "observation_time"], kind="stable")
    for direction, g in d.groupby("direction"):
        for col in VARS:
            x = g[col].astype(float)
            diff = g.groupby("regime_start_ns", sort=False)[col].diff()
            q = x.quantile([0.01, 0.10, 0.50, 0.90, 0.99])
            rows.append({
                "version": version, "year": year,
                "direction": int(direction), "variable": col,
                "count": len(x), "mean": x.mean(), "std": x.std(),
                "min": x.min(), "p01": q.loc[0.01], "p10": q.loc[0.10],
                "p50": q.loc[0.50], "p90": q.loc[0.90],
                "p99": q.loc[0.99], "max": x.max(),
                "negative_count": int((x < -1e-12).sum()),
                "negative_rate": float((x < -1e-12).mean()),
                "monotonicity_violations": int((diff < -1e-12).sum()),
            })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", nargs="+", type=int, required=True)
    args = ap.parse_args()
    rows: list[dict] = []
    for year in args.years:
        repaired_path = year_atlas_path(year)
        assert repaired_path.exists(), repaired_path
        pre = legacy_year(year)
        post = pd.read_parquet(
            repaired_path,
            columns=["observation_time", "regime_start_ns", "direction", *VARS],
        )
        rows.extend(summarize(pre, "legacy_pre_fix", year))
        rows.extend(summarize(post, "CODEX_5_X_repaired", year))
    out = pd.DataFrame(rows)
    out.to_parquet(RESULTS / "CODEX_5_X_pre_post_excursion_distributions.parquet",
                   index=False)
    repaired = out[out["version"] == "CODEX_5_X_repaired"]
    gate = {
        "years": args.years,
        "repaired_negative_count": int(repaired["negative_count"].sum()),
        "repaired_monotonicity_violations": int(
            repaired["monotonicity_violations"].sum()),
        "pass": bool((repaired["negative_count"] == 0).all()
                     and (repaired["monotonicity_violations"] == 0).all()),
    }
    write_json(RESULTS / "CODEX_5_X_excursion_distribution_gate.json", gate)
    pivot = out.pivot_table(
        index=["year", "direction", "variable"], columns="version",
        values=["p50", "negative_rate", "monotonicity_violations"],
    )
    report = f"""# CODEX 5.X — Pre/Post Excursion Distribution Audit

Years: {', '.join(map(str, args.years))}

Repaired gate: `{'PASS' if gate['pass'] else 'FAIL'}`

- repaired negative cells: {gate['repaired_negative_count']}
- repaired monotonicity violations: {gate['repaired_monotonicity_violations']}

`current_mfe/current_mae` are the historical feature names; explicit
`running_mfe/running_mae` aliases carry the same cumulative values.

{pivot.round(6).to_markdown()}
"""
    (RESULTS / "CODEX_5_X_pre_post_excursion_report.md").write_text(
        report, encoding="utf-8")
    print(gate)


if __name__ == "__main__":
    main()

