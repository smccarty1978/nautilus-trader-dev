"""Crucial test: bar1-close-anchor C on WITH-DELAY data vs no-delay data.

If the with-delay V_A-anchor C result (+$61K) was a V-shape recovery
selection artifact, then computing C with bar1_close anchor on the
SAME with-delay data should produce a number close to the no-delay
results (~$22K).

If with-delay bar1_close-anchor C ≈ +$61K, then the +$61K isn't a
V-shape artifact — it's a function of cp_ts timing (with-delay puts
cp_ts at bar1_close + 331s vs no-delay's + 301s).

Anchor combinations on each dataset:

  1. WITH-DELAY data, V_A-anchor:    +$61K (known)
  2. WITH-DELAY data, bar1-anchor:   ?
  3. NO-DELAY data, V_A-anchor:      +$22K (known)
  4. NO-DELAY data, bar1-anchor:     +$19K (known)

(2) is the missing piece.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

NQ_MULT = 20.0
COMMISSION = 5.0
OUT = Path("studies/v_a_excursion_regime/results_v0")


def metrics(df, pnl_col, ts_col="entry_ts"):
    if not len(df):
        return {"n": 0, "total": 0.0, "per_tr": 0.0, "wr_pct": 0.0,
                "max_dd": 0.0, "y2024": 0.0, "y2025": 0.0,
                "y2026": 0.0, "pos_months": 0, "total_months": 0}
    df = df.sort_values(ts_col).copy()
    total = df[pnl_col].sum()
    n = len(df)
    wr_pct = (df[pnl_col] > 0).mean() * 100
    df["cum"] = df[pnl_col].cumsum()
    df["cum_max"] = df["cum"].cummax()
    max_dd = float((df["cum"] - df["cum_max"]).min())
    y = df.groupby("year")[pnl_col].sum()
    df["entry_dt"] = pd.to_datetime(df[ts_col], unit="ns", utc=True)
    df["month"] = df["entry_dt"].dt.to_period("M")
    monthly = df.groupby("month")[pnl_col].sum()
    return {
        "n": n, "total": float(total), "per_tr": float(total / n),
        "wr_pct": float(wr_pct), "max_dd": max_dd,
        "y2024": float(y.get(2024, 0.0)),
        "y2025": float(y.get(2025, 0.0)),
        "y2026": float(y.get(2026, 0.0)),
        "pos_months": int((monthly > 0).sum()),
        "total_months": int(len(monthly)),
    }


def build_bar1_close_lookup(suffix=""):
    rows = []
    for yr in (2024, 2025, 2026):
        snap = pd.read_parquet(
            f"collectors/collector_v2/results/v_a_v0{suffix}_{yr}/"
            f"snapshots.parquet")
        b1 = snap[snap["kind"] == "bar1_check"][
            ["decision_ts", "direction", "bar1_c", "confirmed"]].copy()
        b1 = b1[b1["confirmed"]]
        b1["year"] = yr
        rows.append(b1)
    out = pd.concat(rows, ignore_index=True)
    out = out.rename(columns={"bar1_c": "bar1_close_px"})
    return out[["decision_ts", "direction", "bar1_close_px", "year"]]


def load_data_with_bar1(features_path, trades_path_template, suffix=""):
    """Load checkpoint features + bar1_close from snapshot lookup."""
    df = pd.read_parquet(features_path)
    df = df.sort_values(["entry_ts", "year"]).drop_duplicates(
        subset="entry_ts", keep="first").reset_index(drop=True)

    # Load V_A trades to get decision_ts
    tr_rows = []
    for yr in (2024, 2025, 2026):
        tr = pd.read_parquet(trades_path_template.format(yr))[
            ["entry_ts", "decision_ts"]]
        tr_rows.append(tr)
    tr_full = pd.concat(tr_rows, ignore_index=True).drop_duplicates(
        subset="entry_ts", keep="first")
    df = df.merge(tr_full, on="entry_ts", how="left")

    b1 = build_bar1_close_lookup(suffix=suffix)
    df = df.merge(b1[["decision_ts", "bar1_close_px"]].drop_duplicates(
        subset="decision_ts"), on="decision_ts", how="left")
    return df


def add_anchor_features(df):
    """Add bar1-close anchored unr_pnl at +5m. Need close@5m which we
    back-derive from f_unr_pnl_T_5m and fill_px:
      f_unr_pnl_T_5m = (close - fill_px) * direction * NQ_MULT
      → close = fill_px + f_unr_pnl_T_5m * direction / NQ_MULT
    """
    df = df.copy()
    df["close_at_5m"] = (df["fill_px"]
                          + df["f_unr_pnl_T_5m"]
                            * df["direction"] / NQ_MULT)
    df["f_unr_pnl_anc_T_5m"] = (
        (df["close_at_5m"] - df["bar1_close_px"])
        * df["direction"] * NQ_MULT)
    return df


def report_strategy(df, label, threshold_col, threshold_val,
                       pnl_col="d_pnl_5m"):
    alive = df[df["alive_5m"]].copy()
    sub = alive[alive[threshold_col] >= threshold_val]
    m = metrics(sub, pnl_col)
    pos = f"{m['pos_months']}/{m['total_months']}"
    print(f"  {label:<48}  n={m['n']:>5,}  ${m['total']:>+10,.0f}  "
          f"{m['per_tr']:>+6.2f}/tr  WR={m['wr_pct']:>4.1f}%  "
          f"DD ${m['max_dd']:>+8,.0f}  "
          f"24=${m['y2024']:>+7,.0f}  25=${m['y2025']:>+7,.0f}  "
          f"26=${m['y2026']:>+7,.0f}  +mo={pos:>6}")
    return m


def main():
    t0 = time.time()
    print("=" * 78)
    print("CONSTANT-ANCHOR C — WITH-DELAY vs NO-DELAY data")
    print("=" * 78)

    # WITH-DELAY data
    print("\n--- Loading WITH-DELAY data ---", flush=True)
    df_old = load_data_with_bar1(
        OUT / "checkpoint_features.parquet",
        "collectors/collector_v2/results/v_a_v0_{}/trades.parquet",
        suffix="")
    print(f"  trades: {len(df_old):,}, bar1_close non-null: "
          f"{df_old['bar1_close_px'].notna().sum():,}")
    assert df_old["bar1_close_px"].notna().all(), "missing bar1_close (old)"
    df_old = add_anchor_features(df_old)
    # delay shift: V_A entry - bar1_close (signed by direction)
    delay_shift_old = ((df_old["fill_px"] - df_old["bar1_close_px"])
                          * df_old["direction"])
    print(f"  fill_px - bar1_close (signed): "
          f"median {delay_shift_old.median():.4f}  "
          f"mean {delay_shift_old.mean():.4f}  "
          f"p10 {delay_shift_old.quantile(0.1):.4f}  "
          f"p90 {delay_shift_old.quantile(0.9):.4f}")

    # NO-DELAY data
    print("\n--- Loading NO-DELAY data ---", flush=True)
    df_new = load_data_with_bar1(
        OUT / "checkpoint_features_nodelay.parquet",
        "collectors/collector_v2/results/v_a_v0_nodelay_{}/trades.parquet",
        suffix="_nodelay")
    print(f"  trades: {len(df_new):,}, bar1_close non-null: "
          f"{df_new['bar1_close_px'].notna().sum():,}")
    assert df_new["bar1_close_px"].notna().all(), "missing bar1_close (new)"
    df_new = add_anchor_features(df_new)
    delay_shift_new = ((df_new["fill_px"] - df_new["bar1_close_px"])
                          * df_new["direction"])
    print(f"  fill_px - bar1_close (signed): "
          f"median {delay_shift_new.median():.4f}  "
          f"mean {delay_shift_new.mean():.4f}  "
          f"p10 {delay_shift_new.quantile(0.1):.4f}  "
          f"p90 {delay_shift_new.quantile(0.9):.4f}")

    # IS-q80 thresholds (separately for each dataset and anchor)
    is_old = df_old[df_old["alive_5m"] & df_old["year"].isin(
        [2024, 2025])]
    thr_old_va = is_old["f_unr_pnl_T_5m"].quantile(0.80)
    thr_old_anc = is_old["f_unr_pnl_anc_T_5m"].quantile(0.80)
    is_new = df_new[df_new["alive_5m"] & df_new["year"].isin(
        [2024, 2025])]
    thr_new_va = is_new["f_unr_pnl_T_5m"].quantile(0.80)
    thr_new_anc = is_new["f_unr_pnl_anc_T_5m"].quantile(0.80)

    print(f"\n  IS-q80 thresholds:")
    print(f"    WITH-DELAY V_A-anchor:   ${thr_old_va:.0f}")
    print(f"    WITH-DELAY bar1-anchor:  ${thr_old_anc:.0f}")
    print(f"    NO-DELAY  V_A-anchor:    ${thr_new_va:.0f}")
    print(f"    NO-DELAY  bar1-anchor:   ${thr_new_anc:.0f}")

    print(f"\n{'='*120}")
    print("FOUR-WAY COMPARISON")
    print(f"{'='*120}")
    m_old_va = report_strategy(
        df_old, "WITH-DELAY  V_A-anchor C    >= IS-q80",
        "f_unr_pnl_T_5m", thr_old_va)
    m_old_anc = report_strategy(
        df_old, "WITH-DELAY  bar1-anchor C   >= IS-q80",
        "f_unr_pnl_anc_T_5m", thr_old_anc)
    m_new_va = report_strategy(
        df_new, "NO-DELAY    V_A-anchor C    >= IS-q80",
        "f_unr_pnl_T_5m", thr_new_va)
    m_new_anc = report_strategy(
        df_new, "NO-DELAY    bar1-anchor C   >= IS-q80",
        "f_unr_pnl_anc_T_5m", thr_new_anc)

    print(f"\n{'='*120}")
    print("INTERPRETATION")
    print(f"{'='*120}")
    delta_old = m_old_anc["total"] - m_old_va["total"]
    delta_new = m_new_anc["total"] - m_new_va["total"]
    print(f"  WITH-DELAY:  bar1-anchor − V_A-anchor = ${delta_old:+,.0f}")
    print(f"  NO-DELAY:    bar1-anchor − V_A-anchor = ${delta_new:+,.0f}")
    print()
    print(f"  If bar1-anchor on WITH-DELAY ≈ +$61K: V-shape hypothesis FAILS")
    print(f"    (i.e., the C edge is from cp_ts timing, not fill anchor)")
    print(f"  If bar1-anchor on WITH-DELAY ≈ +$22K: V-shape hypothesis HOLDS")
    print(f"    (i.e., V_A-anchor was selecting v-shape recoveries)")

    # Critical question: what's the "true" C result?
    # Theoretically the cleanest spec is bar1-anchor + cp_ts at bar1_close+300s
    # This is approximately the NO-DELAY bar1-anchor C (cp_ts off by 1s)
    print(f"\n  Cleanest 'true' C: {m_new_anc['total']:+,.0f} "
          f"(no-delay V_A entry ≈ bar1_close + 1s, cp_ts ≈ bar1_close + 301s)")

    # Per-year breakdown of all four
    print(f"\n{'='*120}")
    print("PER-YEAR DETAIL")
    print(f"{'='*120}")
    print(f"  {'variant':<40}  {'2024':>10}  {'2025':>10}  {'2026':>10}  "
          f"{'TOTAL':>10}")
    for label, m in [
        ("WITH-DELAY V_A-anchor", m_old_va),
        ("WITH-DELAY bar1-anchor", m_old_anc),
        ("NO-DELAY V_A-anchor", m_new_va),
        ("NO-DELAY bar1-anchor", m_new_anc),
    ]:
        print(f"  {label:<40}  ${m['y2024']:>+8,.0f}  "
              f"${m['y2025']:>+8,.0f}  ${m['y2026']:>+8,.0f}  "
              f"${m['total']:>+8,.0f}")

    print(f"\n[done] runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
