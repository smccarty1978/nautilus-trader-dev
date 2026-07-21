"""Shared utilities for MTF context analyses."""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

NQ_MULT = 20.0
COMMISSION = 5.0
TRADES_FILE = "studies/1m_mtf_context/results/trades_all.parquet"
SKIPPED_FILE = "studies/1m_mtf_context/results/skipped_all.parquet"


def load_trades() -> pd.DataFrame:
    """Load combined trades. Raises clearly if not present."""
    if not Path(TRADES_FILE).exists():
        raise FileNotFoundError(
            f"{TRADES_FILE} missing — run collection first.")
    return pd.read_parquet(TRADES_FILE)


def load_skipped() -> pd.DataFrame:
    if not Path(SKIPPED_FILE).exists():
        return pd.DataFrame()
    return pd.read_parquet(SKIPPED_FILE)


def cohens_d(g1: np.ndarray, g2: np.ndarray) -> float:
    g1 = np.asarray(g1, dtype=np.float64)
    g2 = np.asarray(g2, dtype=np.float64)
    g1 = g1[~np.isnan(g1)]
    g2 = g2[~np.isnan(g2)]
    if len(g1) < 2 or len(g2) < 2:
        return float("nan")
    n1, n2 = len(g1), len(g2)
    m1, m2 = g1.mean(), g2.mean()
    v1, v2 = g1.var(ddof=1), g2.var(ddof=1)
    pooled = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    if pooled == 0:
        return 0.0
    return (m1 - m2) / pooled


def bracket_pnl(trades: pd.DataFrame, tag: str,
                 pt_atr: float, sl_atr: float) -> np.ndarray:
    """Dollar PnL for a given bracket using pre-computed race result."""
    res = trades[f"bracket_{tag}_result"].values
    atr = trades["atr_at_flip"].values
    reg_pnl = trades["regime_pnl_dollars"].values
    pnl = np.zeros(len(trades))
    pnl[res == "PT"] = pt_atr * atr[res == "PT"] * NQ_MULT - COMMISSION
    pnl[res == "SL"] = -sl_atr * atr[res == "SL"] * NQ_MULT - COMMISSION
    pnl[res == "neither"] = reg_pnl[res == "neither"]
    return pnl


def pt_first_pct(trades: pd.DataFrame, tag: str) -> float:
    res = trades[f"bracket_{tag}_result"].values
    return (res == "PT").mean() * 100


def summarize_segment(label: str, df: pd.DataFrame,
                       tag: str, pt_atr: float, sl_atr: float) -> dict:
    pnl = bracket_pnl(df, tag, pt_atr, sl_atr)
    avg = pnl.mean()
    total = pnl.sum()
    wr = (pnl > 0).mean() * 100
    gw = pnl[pnl > 0].sum()
    gl = abs(pnl[pnl <= 0].sum())
    pf = gw / gl if gl > 0 else 999.0
    mfe = df["peak_mfe_atr"].mean()
    res = df[f"bracket_{tag}_result"].values
    pt_pct = (res == "PT").mean() * 100
    sl_pct = (res == "SL").mean() * 100
    reg_pct = (res == "neither").mean() * 100
    return {
        "label": label, "n": len(df),
        "mean_mfe": mfe,
        "pt_pct": pt_pct, "sl_pct": sl_pct, "regime_pct": reg_pct,
        "avg": avg, "total": total, "wr": wr, "pf": pf,
    }


def print_segment_row(s: dict):
    print(f"  {s['label']:<36} N={s['n']:>6,}  MFE={s['mean_mfe']:5.2f}  "
          f"PT={s['pt_pct']:5.1f}%  SL={s['sl_pct']:5.1f}%  "
          f"Reg={s['regime_pct']:5.1f}%  "
          f"Avg=${s['avg']:>+6.1f}  Tot=${s['total']:>+10,.0f}  "
          f"PF={s['pf']:5.2f}")
