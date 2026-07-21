"""nt_parity_audit.parquet: for every policy, confirm every RETAINED trade
(i.e. one this policy's skip filter did not skip and that filled) has an
IDENTICAL entry_ts/fill_price/exit_ts/exit_price to R0's trade for the same
decision_ts. Retained-trade identity is empirically checked, not assumed --
CollectorV2Strategy holds at most one open position, so skipping an entry
can in principle change subsequent portfolio state and shift a later trade's
entry/exit. This audit is the actual proof, one way or the other.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import pandas as pd
import awf_common as c
from run_nt_adaptive import ALL_POLICIES

WORK_DIR = c.OUT.parent / "_work"

COMPARE_COLS = ["entry_ts", "fill_price", "exit_ts", "exit_price"]


def main():
    trades = pd.read_parquet(WORK_DIR / "nt_trade_results.parquet")
    rows = []

    for period_key in trades["period_key"].unique():
        r0 = trades[(trades["policy"] == "r0") & (trades["period_key"] == period_key)]
        r0_idx = r0.set_index("decision_ts")[COMPARE_COLS]

        for policy in ALL_POLICIES:
            if policy == "r0":
                continue
            pol = trades[(trades["policy"] == policy) & (trades["period_key"] == period_key)]
            if len(pol) == 0:
                continue
            pol_idx = pol.set_index("decision_ts")[COMPARE_COLS]

            joined = pol_idx.join(r0_idx, how="left", lsuffix="_pol", rsuffix="_r0")
            has_r0_match = joined["entry_ts_r0"].notna()
            n_retained = len(joined)
            n_matched_in_r0 = int(has_r0_match.sum())

            mism = pd.Series(False, index=joined.index)
            for col in COMPARE_COLS:
                a, b = joined[f"{col}_pol"], joined[f"{col}_r0"]
                if np.issubdtype(a.dtype, np.floating) or np.issubdtype(b.dtype, np.floating):
                    diff = (a - b).abs() > 1e-6
                else:
                    diff = a != b
                mism = mism | (diff & has_r0_match)

            n_mismatched = int(mism.sum())
            n_exact_match = n_matched_in_r0 - n_mismatched
            n_not_in_r0 = n_retained - n_matched_in_r0  # a retained trade R0 itself didn't take -- would be a real anomaly

            rows.append({
                "policy": policy, "period_key": period_key,
                "n_retained_filled": n_retained,
                "n_matched_in_r0": n_matched_in_r0,
                "n_exact_match": n_exact_match,
                "n_mismatched": n_mismatched,
                "n_not_in_r0_at_all": n_not_in_r0,
                "retained_trade_parity_pct": 100.0 * n_exact_match / n_retained if n_retained else 100.0,
            })

    audit = pd.DataFrame(rows)
    audit.to_parquet(c.OUT / "nt_parity_audit.parquet", index=False)

    overall_pct = audit["n_exact_match"].sum() / audit["n_retained_filled"].sum() * 100 if audit["n_retained_filled"].sum() else 100.0
    print(audit.to_string())
    print(f"\nOverall retained_trade_parity: {overall_pct:.4f}%")
    print(f"critical_execution_violations (mismatched retained trades): {audit['n_mismatched'].sum()}")
    print(f"trades retained but not present in R0 at all: {audit['n_not_in_r0_at_all'].sum()}")

    with open(WORK_DIR / "parity_summary.txt", "w") as f:
        f.write(f"overall_retained_trade_parity_pct={overall_pct}\n")
        f.write(f"total_mismatched={audit['n_mismatched'].sum()}\n")
        f.write(f"total_not_in_r0={audit['n_not_in_r0_at_all'].sum()}\n")


if __name__ == "__main__":
    main()
