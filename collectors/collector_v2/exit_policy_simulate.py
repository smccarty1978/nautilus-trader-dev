"""Simulate exit-policy rules using model scores from
exit_policy_train.py.

For each test-set checkpoint with model scores, evaluate three
policy families:

  P1. Exit when score(remaining_ev_atr) < threshold
      (regression model — lower predicted EV → exit early)
  P2. Exit when score(future_giveback_risk) > threshold
      (binary — high giveback risk → exit)
  P3. Exit when score(exit_now_better_than_hold) > threshold
      (binary — model says exit beats hold)

Each policy turns checkpoint scores into trade-level exit times:
  - Walk a trade's checkpoints in order
  - On the FIRST checkpoint where the policy fires, exit at that
    checkpoint's `cur_close_price`
  - Otherwise, hold to the trade's actual exit (regime exit baseline)

Then compute per-trade PnL under the policy and compare to:
  - baseline (hold-to-regime-exit, = trade.trade_net_pnl in dataset)
  - SL=2.0 ATR safety overlay (cut at first checkpoint where
    cur_mae_atr >= 2.0)

Output: collectors/collector_v2/results/exit_policy/
        sim_<label>.parquet (per-trade results)
        sim_<label>_summary.json
"""

from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
os.chdir(project_root)

OUT = Path("collectors/collector_v2/results/exit_policy")
MODELS_DIR = OUT / "models"


# Cost model used for hypothetical exit at checkpoint
COMMISSION = 5.0
TICK_DOLLAR_DEFAULT = 5.0  # NQ default; per-product handled by atr*mult


def simulate_policy(test_df: pd.DataFrame, score_col: str,
                       threshold: float, *,
                       direction: str = "above",
                       multiplier: float = 20.0,
                       tick_dollar: float = 5.0) -> pd.DataFrame:
    """Simulate one policy. Returns one row per trade."""
    rows = []
    for tid, g in test_df.sort_values(
            ["trade_event_id", "decision_ts"]).groupby(
            "trade_event_id"):
        g = g.reset_index(drop=True)
        atr = float(g["trade_atr_at_signal"].iloc[0])
        if not (atr > 0):
            continue
        d = int(g["trade_direction"].iloc[0])
        fp = float(g["trade_fill_price"].iloc[0])
        baseline_pnl = float(g["trade_net_pnl"].iloc[0])
        # Walk checkpoints; fire on first that crosses threshold
        exit_idx = None
        for i, row in g.iterrows():
            score = row.get(score_col)
            if pd.isna(score):
                continue
            cond = (score >= threshold if direction == "above"
                       else score <= threshold)
            if cond:
                exit_idx = i
                break
        if exit_idx is None:
            policy_pnl = baseline_pnl
            exit_kind = "hold_to_baseline"
        else:
            cp = g.iloc[exit_idx]
            cur_close = float(cp["cur_close_price"])
            gross = (cur_close - fp) * d * multiplier
            cost = COMMISSION + tick_dollar  # 1-tick exit slip
            policy_pnl = gross - cost
            exit_kind = "policy_exit"
        rows.append({
            "trade_event_id": tid,
            "baseline_pnl": baseline_pnl,
            "policy_pnl": policy_pnl,
            "delta": policy_pnl - baseline_pnl,
            "exit_kind": exit_kind,
            "exit_idx": (-1 if exit_idx is None else exit_idx),
            "n_checkpoints": len(g),
        })
    return pd.DataFrame(rows)


def simulate_sl_overlay(test_df: pd.DataFrame, sl_atr: float = 2.0,
                            *, multiplier: float = 20.0,
                            tick_dollar: float = 5.0) -> pd.DataFrame:
    """SL=X ATR safety overlay — cut at first checkpoint where
    cur_mae_atr >= sl_atr."""
    rows = []
    for tid, g in test_df.sort_values(
            ["trade_event_id", "decision_ts"]).groupby(
            "trade_event_id"):
        g = g.reset_index(drop=True)
        atr = float(g["trade_atr_at_signal"].iloc[0])
        if not (atr > 0):
            continue
        d = int(g["trade_direction"].iloc[0])
        fp = float(g["trade_fill_price"].iloc[0])
        baseline_pnl = float(g["trade_net_pnl"].iloc[0])
        # Find first cp where cur_mae_atr >= sl_atr
        hit = g[g["cur_mae_atr"] >= sl_atr]
        if len(hit) == 0:
            policy_pnl = baseline_pnl
            exit_kind = "hold"
        else:
            # Exit at SL price (NOT cur_close — assume SL fill at
            # exact threshold)
            sl_price = fp - d * sl_atr * atr
            gross = (sl_price - fp) * d * multiplier
            cost = COMMISSION + 2 * tick_dollar  # 2-tick SL slip
            policy_pnl = gross - cost
            exit_kind = "sl"
        rows.append({
            "trade_event_id": tid,
            "baseline_pnl": baseline_pnl,
            "policy_pnl": policy_pnl,
            "delta": policy_pnl - baseline_pnl,
            "exit_kind": exit_kind,
        })
    return pd.DataFrame(rows)


def stats_pnl(s: pd.Series) -> dict:
    s = s.dropna()
    n = len(s)
    if n == 0:
        return {"n": 0}
    wins = s[s > 0]; losses = s[s < 0]
    pf = (wins.sum() / abs(losses.sum())
            if len(losses) and losses.sum() != 0 else float("inf"))
    cum = s.cumsum().values
    peak = np.maximum.accumulate(cum)
    mdd = float((cum - peak).min())
    return {"n": n, "wr": float((s > 0).mean()),
              "mean": float(s.mean()), "median": float(s.median()),
              "sum": float(s.sum()), "pf": float(pf),
              "max_dd": mdd,
              "avg_win": float(wins.mean()) if len(wins) else float("nan"),
              "avg_loss": float(losses.mean()) if len(losses)
                          else float("nan")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True,
                     help="model label (matches train output)")
    ap.add_argument("--multiplier", type=float, default=20.0)
    ap.add_argument("--tick-dollar", type=float, default=5.0)
    args = ap.parse_args()
    pred_p = MODELS_DIR / f"{args.label}_test_predictions.parquet"
    if not pred_p.exists():
        print(f"Predictions not found: {pred_p}")
        sys.exit(1)
    test_df = pd.read_parquet(pred_p)
    print(f"Loaded {len(test_df):,} test checkpoints")

    # Baseline (hold to regime exit) per-trade
    base_per_trade = test_df.groupby(
        "trade_event_id")["trade_net_pnl"].first()
    base_stats = stats_pnl(base_per_trade)
    print(f"\nBaseline: n={base_stats['n']:,}, "
           f"mean=${base_stats['mean']:.2f}, "
           f"PF={base_stats['pf']:.2f}, "
           f"total=${base_stats['sum']:,.0f}, "
           f"DD=${base_stats['max_dd']:,.0f}")

    summary = {"label": args.label, "baseline": base_stats,
                  "policies": {}}

    # Policy P1: predicted remaining_ev_atr < threshold
    if "score_lgbm_remaining_ev_atr" in test_df.columns:
        for thr in [-0.25, 0.0, 0.25]:
            sim = simulate_policy(
                test_df, "score_lgbm_remaining_ev_atr",
                threshold=thr, direction="below",
                multiplier=args.multiplier,
                tick_dollar=args.tick_dollar)
            s = stats_pnl(sim["policy_pnl"])
            n_exited = int((sim["exit_kind"] == "policy_exit").sum())
            summary["policies"][f"P1_remaining_ev_lt_{thr}"] = {
                "stats": s, "n_exited_early": n_exited,
                "delta_total": float(sim["delta"].sum()),
            }
            print(f"\nP1 ev<{thr}: n={s['n']:,}, "
                   f"mean=${s['mean']:.2f}, PF={s['pf']:.2f}, "
                   f"total=${s['sum']:,.0f}, "
                   f"early_exit={n_exited:,}, "
                   f"delta=${sim['delta'].sum():,.0f}")

    # Policy P2: predicted giveback risk > threshold
    if "score_lgbm_future_giveback_risk" in test_df.columns:
        for thr in [0.5, 0.6, 0.7, 0.8]:
            sim = simulate_policy(
                test_df, "score_lgbm_future_giveback_risk",
                threshold=thr, direction="above",
                multiplier=args.multiplier,
                tick_dollar=args.tick_dollar)
            s = stats_pnl(sim["policy_pnl"])
            n_exited = int((sim["exit_kind"] == "policy_exit").sum())
            summary["policies"][f"P2_giveback_gt_{thr}"] = {
                "stats": s, "n_exited_early": n_exited,
                "delta_total": float(sim["delta"].sum()),
            }
            print(f"\nP2 give>{thr}: n={s['n']:,}, "
                   f"mean=${s['mean']:.2f}, PF={s['pf']:.2f}, "
                   f"total=${s['sum']:,.0f}, "
                   f"early_exit={n_exited:,}")

    # Policy P3: predicted exit_now_better > threshold
    if "score_lgbm_exit_now_better_than_hold" in test_df.columns:
        for thr in [0.5, 0.6, 0.7, 0.8]:
            sim = simulate_policy(
                test_df, "score_lgbm_exit_now_better_than_hold",
                threshold=thr, direction="above",
                multiplier=args.multiplier,
                tick_dollar=args.tick_dollar)
            s = stats_pnl(sim["policy_pnl"])
            n_exited = int((sim["exit_kind"] == "policy_exit").sum())
            summary["policies"][f"P3_exit_now_gt_{thr}"] = {
                "stats": s, "n_exited_early": n_exited,
                "delta_total": float(sim["delta"].sum()),
            }
            print(f"\nP3 exit>{thr}: n={s['n']:,}, "
                   f"mean=${s['mean']:.2f}, PF={s['pf']:.2f}, "
                   f"total=${s['sum']:,.0f}, "
                   f"early_exit={n_exited:,}")

    # SL=2.0 ATR overlay
    sim_sl = simulate_sl_overlay(test_df, sl_atr=2.0,
                                       multiplier=args.multiplier,
                                       tick_dollar=args.tick_dollar)
    s = stats_pnl(sim_sl["policy_pnl"])
    n_sl = int((sim_sl["exit_kind"] == "sl").sum())
    summary["policies"]["SL_2_0_ATR_safety"] = {
        "stats": s, "n_sl_hit": n_sl,
        "delta_total": float(sim_sl["delta"].sum()),
    }
    print(f"\nSL=2.0: n={s['n']:,}, mean=${s['mean']:.2f}, "
           f"PF={s['pf']:.2f}, total=${s['sum']:,.0f}, "
           f"sl_hit={n_sl:,}")

    out_p = OUT / f"sim_{args.label}_summary.json"
    with open(out_p, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nSummary: {out_p}")


if __name__ == "__main__":
    main()
