"""Smoke parity harness — gate before any full-year offline study.

Workflow for any new strategy/study:

  1. Pick a 1-week window (suggest 2024-01-08 to 2024-01-15 — Jan
     2024 has full RTH coverage, no major holidays mid-week).
  2. Run offline collector on that window.
  3. Run NT runtime strategy on that window.
  4. Call `compare_smoke_runs(offline_df, nt_df)` — fails on any
     systematic mismatch.

If smoke parity fails, do NOT proceed to full-year offline study.
Fix the offline collector first.

`compare_smoke_runs` returns a dict with:
  - n_offline, n_nt, count_match
  - matched_pairs (offline-nt pairs joined by signal_time)
  - outcome_agreement_pct
  - per-feature parity (if `feature_cols` provided)
  - mean_pnl_offline, mean_pnl_nt, mean_pnl_delta
  - violations: list of mismatched-pair dicts (max 20 reported)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence, Optional
import numpy as np
import pandas as pd


@dataclass
class SmokeParityResult:
    n_offline: int
    n_nt: int
    count_delta: int
    matched_pairs: int
    outcome_agreement_pct: float
    pnl_correlation: float
    mean_pnl_offline: float
    mean_pnl_nt: float
    mean_pnl_delta: float
    feature_parity: dict = field(default_factory=dict)
    violations: list = field(default_factory=list)
    passed: bool = False
    fail_reasons: list = field(default_factory=list)


def compare_smoke_runs(
    offline_df: pd.DataFrame,
    nt_df: pd.DataFrame,
    *,
    join_key_offline: str = "fill_ts",
    join_key_nt: str = "entry_ts",
    pnl_col_offline: str = "final_net_pnl",
    pnl_col_nt: str = "net_pnl",
    direction_col_offline: str = "direction",
    direction_col_nt: str = "direction",
    outcome_col_offline: Optional[str] = None,
    outcome_col_nt: Optional[str] = None,
    feature_cols: Optional[Sequence[str]] = None,
    join_tolerance_ns: int = 2 * 1_000_000_000,  # 2s
    pnl_per_trade_tolerance: float = 1.50,        # $1.50/trade drag
    count_pct_tolerance: float = 0.05,            # 5% count drift
    outcome_agreement_min: float = 0.95,
) -> SmokeParityResult:
    """Run a battery of parity checks. Returns SmokeParityResult.
    `passed` is True only if all checks within tolerance.
    """
    n_off = len(offline_df)
    n_nt = len(nt_df)
    count_delta = n_nt - n_off
    fail_reasons: list = []

    # 1) Count parity
    if n_off == 0:
        fail_reasons.append("offline_df empty")
    elif n_nt == 0:
        fail_reasons.append("nt_df empty")
    else:
        if abs(count_delta) / n_off > count_pct_tolerance:
            fail_reasons.append(
                f"count drift {100*abs(count_delta)/n_off:.1f}% "
                f"exceeds tolerance {100*count_pct_tolerance:.1f}%")

    # 2) Joined-pair check
    matched = 0
    outcome_agreement = float("nan")
    pnl_corr = float("nan")
    mean_off = float(offline_df[pnl_col_offline].mean()) \
        if n_off else float("nan")
    mean_nt = float(nt_df[pnl_col_nt].mean()) if n_nt else float("nan")
    mean_delta = mean_nt - mean_off if not np.isnan(mean_off) else float("nan")
    feature_parity_dict: dict = {}
    violations: list = []

    if n_off and n_nt:
        # Tolerance-based join on timestamp
        off_ts = np.asarray(offline_df[join_key_offline].values,
                              dtype="int64")
        nt_ts = np.asarray(nt_df[join_key_nt].values, dtype="int64")
        # For each offline row, find closest NT row within tolerance
        off_sorted = np.argsort(off_ts)
        nt_sorted_idx = np.argsort(nt_ts)
        nt_ts_sorted = nt_ts[nt_sorted_idx]
        pairs = []
        for oi in off_sorted:
            t = off_ts[oi]
            j = int(np.searchsorted(nt_ts_sorted, t, side="left"))
            best = None
            for cand in [j - 1, j]:
                if 0 <= cand < len(nt_ts_sorted):
                    diff = abs(int(nt_ts_sorted[cand]) - int(t))
                    if (diff <= join_tolerance_ns
                            and (best is None or diff < best[1])):
                        best = (int(nt_sorted_idx[cand]), diff)
            if best is not None:
                pairs.append((int(oi), best[0]))
        matched = len(pairs)
        if matched:
            off_idx = [p[0] for p in pairs]
            nt_idx = [p[1] for p in pairs]
            mo = offline_df.iloc[off_idx].reset_index(drop=True)
            mn = nt_df.iloc[nt_idx].reset_index(drop=True)
            # Direction agreement
            if (direction_col_offline in mo.columns
                    and direction_col_nt in mn.columns):
                dir_match = (mo[direction_col_offline]
                                == mn[direction_col_nt]).mean()
                if dir_match < 0.99:
                    fail_reasons.append(
                        f"direction agreement {100*dir_match:.1f}% "
                        f"on matched pairs")
            # Outcome agreement (if both columns present)
            if (outcome_col_offline and outcome_col_nt
                    and outcome_col_offline in mo.columns
                    and outcome_col_nt in mn.columns):
                outcome_agreement = float(
                    (mo[outcome_col_offline]
                     == mn[outcome_col_nt]).mean())
                if outcome_agreement < outcome_agreement_min:
                    fail_reasons.append(
                        f"outcome agreement "
                        f"{100*outcome_agreement:.1f}% < "
                        f"{100*outcome_agreement_min:.0f}%")
            # PnL correlation
            if (pnl_col_offline in mo.columns
                    and pnl_col_nt in mn.columns):
                pnl_corr = float(
                    np.corrcoef(mo[pnl_col_offline],
                                  mn[pnl_col_nt])[0, 1])
                if pnl_corr < 0.95:
                    fail_reasons.append(
                        f"PnL correlation {pnl_corr:.3f} < 0.95")
            # Per-trade PnL drag
            if (pnl_col_offline in mo.columns
                    and pnl_col_nt in mn.columns):
                drag = (mn[pnl_col_nt] - mo[pnl_col_offline]).mean()
                if abs(drag) > pnl_per_trade_tolerance:
                    fail_reasons.append(
                        f"matched-pair PnL drag ${drag:.2f}/trade "
                        f"exceeds tolerance "
                        f"${pnl_per_trade_tolerance:.2f}")
            # Feature parity (numeric)
            if feature_cols:
                for f in feature_cols:
                    if f in mo.columns and f in mn.columns:
                        a = pd.to_numeric(mo[f], errors="coerce")
                        b = pd.to_numeric(mn[f], errors="coerce")
                        valid = (~a.isna()) & (~b.isna())
                        if valid.any():
                            diff = (b - a).abs()
                            tol = (a.abs().clip(lower=1.0)
                                     * 1e-6 + 1e-6)
                            mismatch = (diff > tol).sum()
                            feature_parity_dict[f] = {
                                "n_compared": int(valid.sum()),
                                "n_mismatch": int(mismatch),
                                "max_abs_diff": float(diff.max()),
                                "mean_abs_diff": float(diff.mean()),
                            }
                            if (mismatch > 0
                                    and mismatch / valid.sum() > 0.01):
                                fail_reasons.append(
                                    f"feature {f} mismatch rate "
                                    f"{100*mismatch/valid.sum():.1f}%")
            # Capture sample violations
            if outcome_agreement_min > 0 and outcome_col_offline:
                bad = mo[mo[outcome_col_offline]
                           != mn[outcome_col_nt]].head(20)
                if len(bad):
                    for _, r in bad.iterrows():
                        violations.append(dict(r))

    passed = len(fail_reasons) == 0
    return SmokeParityResult(
        n_offline=n_off,
        n_nt=n_nt,
        count_delta=count_delta,
        matched_pairs=matched,
        outcome_agreement_pct=outcome_agreement,
        pnl_correlation=pnl_corr,
        mean_pnl_offline=mean_off,
        mean_pnl_nt=mean_nt,
        mean_pnl_delta=mean_delta,
        feature_parity=feature_parity_dict,
        violations=violations[:20],
        passed=passed,
        fail_reasons=fail_reasons,
    )


def print_smoke_summary(r: SmokeParityResult) -> None:
    print(f"Offline n: {r.n_offline:,}")
    print(f"NT n:      {r.n_nt:,}")
    print(f"Count Δ:   {r.count_delta:+,}")
    print(f"Matched:   {r.matched_pairs:,}")
    if not np.isnan(r.outcome_agreement_pct):
        print(f"Outcome agreement: "
               f"{100*r.outcome_agreement_pct:.1f}%")
    if not np.isnan(r.pnl_correlation):
        print(f"PnL correlation:    {r.pnl_correlation:.3f}")
    print(f"Mean PnL offline:  ${r.mean_pnl_offline:.2f}")
    print(f"Mean PnL NT:       ${r.mean_pnl_nt:.2f}")
    print(f"Mean PnL Δ:        ${r.mean_pnl_delta:+.2f}/trade")
    if r.feature_parity:
        print("Feature parity (mismatched only):")
        for f, d in r.feature_parity.items():
            if d["n_mismatch"] > 0:
                print(f"  {f}: {d['n_mismatch']}/{d['n_compared']} "
                       f"max_diff={d['max_abs_diff']:.4g}")
    print()
    print(f"PASSED: {r.passed}")
    if r.fail_reasons:
        print("FAIL REASONS:")
        for fr in r.fail_reasons:
            print(f"  - {fr}")
