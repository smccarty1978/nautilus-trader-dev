"""Phase 10: human-visible case studies (development data only) + a representation check.

Five regimes are chosen by deterministic rules (the median-ranked qualifying regime of each type; see RULES). For each:
  artifacts/cases/<TYPE>.png  1m candles S-30 min .. T+10 min, EMA3/EMA9 of high and low, 1.0A challenge onsets, new extremes, flip
  artifacts/cases/CASE_EVENTS.csv  chronological event table (1.0A challenges; 0.5A counts alongside)
Representation check: for the transition challenge of the DETERIORATING case, the nearest 1.0A challenge (standardised onset
features) among successful challenges of CLEAN_TREND-type regimes; a small distance means the representation cannot tell the
two charts apart.

    python studies/nq_regime_challenge_lifecycle_2023/cases.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "artifacts"
CASES = OUT / "cases"
NS = 1_000_000_000
REP_FEATURES = ["mfe_A", "dist_flip_A", "since_ext_s", "ch_dur_s", "imp_A", "imp_eff", "imp_bars", "ret60_A", "prog_last_A", "prev_max_depth_A",
                "n", "band_w_A", "slope9_A", "ema_sep_A", "ch_vol_ratio", "15m_aligned", "1h_aligned", "atr_pts", "min_since_open"]


def pick(df: pd.DataFrame, rank_col: str) -> int:
    df = df.sort_values(rank_col)
    return int(df.regime_start_ns.iloc[len(df) // 2])


def main() -> None:
    CASES.mkdir(parents=True, exist_ok=True)
    ev = pd.read_parquet(OUT / "CHALLENGE_EVENTS.parquet")
    m = pd.read_parquet(OUT / "LIFECYCLE_1M.parquet")
    led = pd.read_parquet(OUT / "REGIME_LEDGER.parquet").set_index("start_ns")
    e1, e5 = ev[ev.k == 1.0], ev[ev.k == 0.5]
    reg = e1.groupby("regime_start_ns").agg(n1=("n", "max"), gross=("final_gross_A", "first"), mfe_max=("mfe_A", "max"),
                                            new_ext_all_but_last=("res_new_ext", lambda s: bool(s.iloc[:-1].all()) if len(s) > 1 else False),
                                            imp_first=("imp_A", "first"), t_first=("t_onset_s", "first"), last_prog=("prog_last_A", "last"),
                                            prev_prog=("prog_last_A", lambda s: s.iloc[-2] if len(s) > 1 else np.nan))
    reg["n05"] = e5.groupby("regime_start_ns").n.max()
    reg["dur_min"] = (led.loc[reg.index, "duration_s"] / 60).to_numpy()
    reg = reg.reset_index()
    RULES = {
        "CLEAN_TREND": ("n1 >= 4, every 1.0A challenge but the last makes a new extreme, final gross >= 4A", reg[(reg.n1 >= 4) & reg.new_ext_all_but_last & (reg.gross >= 4)], "gross"),
        "DETERIORATING": ("n1 >= 3, MFE >= 3A, final gross < 0, last recovery leg smaller than the one before", reg[(reg.n1 >= 3) & (reg.mfe_max >= 3) & (reg.gross < 0) & (reg.last_prog < reg.prev_prog)], "mfe_max"),
        "ROTATIONAL_CHOP": ("duration >= 30 min, MFE < 1.5A, >= 6 challenges at 0.5A", reg[(reg.dur_min >= 30) & (reg.mfe_max < 1.5) & (reg.n05 >= 6)], "dur_min"),
        "RAPID_TRANSITION": ("duration <= 3 min", reg[reg.dur_min <= 3], "gross"),
        "STRONG_IMPULSE_FAILED_RECOVERY": ("first 1.0A challenge after an impulse >= 2.5A within 5 min, and it never makes a new extreme (regime flips)",
                                           reg[(reg.imp_first >= 2.5) & (reg.t_first <= 300) & (reg.n1 == 1)], "imp_first"),
    }
    rows, chosen = [], {}
    for name, (rule, cand, rank) in RULES.items():
        if cand.empty:
            continue
        S = pick(cand, rank)
        chosen[name] = S
        T = int(led.loc[S, "end_ns"])
        d = int(led.loc[S, "dir"])
        w = m[(m.ts > S - 30 * 60 * NS) & (m.ts <= T + 10 * 60 * NS)]
        x = pd.to_datetime(w.ts, unit="ns", utc=True).dt.tz_convert("America/New_York")
        fig, ax = plt.subplots(figsize=(13, 6))
        up = w.c >= w.o
        ax.vlines(x, w.l, w.h, color="#555", linewidth=0.8)
        ax.vlines(x[up], w.o[up], w.c[up], color="#2a9d8f", linewidth=4)
        ax.vlines(x[~up], w.o[~up], w.c[~up], color="#e76f51", linewidth=4)
        for col, sty in (("e3h", "-"), ("e9h", "--"), ("e3l", "-"), ("e9l", "--")):
            ax.plot(x, w[col], sty, linewidth=0.9, color="#264653" if "h" in col else "#8d99ae", label=col)
        ax.axvline(pd.Timestamp(S, tz="UTC").tz_convert("America/New_York"), color="green" if d > 0 else "red", linewidth=1.2)
        ax.axvline(pd.Timestamp(T, tz="UTC").tz_convert("America/New_York"), color="black", linewidth=1.2, linestyle=":")
        ce = e1[e1.regime_start_ns == S]
        for r in ce.itertuples():
            tx = pd.Timestamp(r.tc_ns, tz="UTC").tz_convert("America/New_York")
            px = d * (d * led.loc[S, "start_close"] + (r.mfe_A - 1.0) * r.atr_pts)
            ax.plot([tx], [px], marker="v" if d > 0 else "^", color="purple", markersize=9)
            ax.annotate(f"C{r.n}{'✓' if r.res_new_ext else '✗'}", (tx, px), textcoords="offset points", xytext=(4, -14 if d > 0 else 8), fontsize=8)
        ax.set_title(f"{name}  {x.iloc[0]:%Y-%m-%d}  dir={'LONG' if d > 0 else 'SHORT'}  gross={cand.set_index('regime_start_ns').loc[S, 'gross']:.2f}A  "
                     f"(green=flip in, dotted=terminal flip, purple=1.0A challenge onset, ✓ new extreme / ✗ transition)", fontsize=9)
        ax.legend(fontsize=7, loc="best")
        fig.tight_layout()
        fig.savefig(CASES / f"{name}.png", dpi=110)
        plt.close(fig)
        for r in ce.itertuples():
            rows.append({"case": name, "rule": rule, "time_ET": f"{pd.Timestamp(r.tc_ns, tz='UTC').tz_convert('America/New_York'):%Y-%m-%d %H:%M:%S}",
                         "dir": d, "challenge_n": r.n, "age_min": round(r.t_onset_s / 60, 1), "mfe_A": round(r.mfe_A, 2), "depth_A": 1.0,
                         "touch_price": round(d * (d * led.loc[S, "start_close"] + (r.mfe_A - 1.0) * r.atr_pts), 2), "since_ext_s": r.since_ext_s,
                         "impulse_A": round(r.imp_A, 2), "impulse_bars": r.imp_bars, "prog_last_A": round(r.prog_last_A, 2) if pd.notna(r.prog_last_A) else None,
                         "dist_flip_A": round(r.dist_flip_A, 2), "band_w_A": round(r.band_w_A, 2), "slope9_A": round(r.slope9_A, 2),
                         "prior_turns_within_0p5A": r.n_turns_0p5, "prior_deeps_near_touch_0p5": r.n_prior_deeps_near_touch_0p5,
                         "vol_ratio_ch_vs_imp": round(r.ch_vol_ratio, 2) if pd.notna(r.ch_vol_ratio) else None,
                         "15m_aligned": ev.loc[r.Index, "15m_aligned"], "1h_aligned": ev.loc[r.Index, "1h_aligned"],
                         "outcome": "NEW_EXTREME" if r.res_new_ext else "TRANSITION", "max_depth_A": round(r.max_depth_A, 2),
                         "new_prog_A": round(r.new_prog_A, 2), "hold_A": round(r.hold_A, 2), "rem_mfe_A": round(r.rem_mfe_A, 2),
                         "n_0p5A_challenges_in_regime": int(reg.set_index("regime_start_ns").loc[S, "n05"])})
    cases = pd.DataFrame(rows)
    cases.to_csv(CASES / "CASE_EVENTS.csv", index=False)

    # ---- representation check
    z = e1[REP_FEATURES].astype(float)
    z = (z - z.mean()) / z.std()
    rep = {}
    if "DETERIORATING" in chosen:
        tgt = e1[(e1.regime_start_ns == chosen["DETERIORATING"]) & (e1.res_new_ext == 0)].index
        clean_regs = RULES["CLEAN_TREND"][1].regime_start_ns
        pool = e1[e1.regime_start_ns.isin(clean_regs) & (e1.res_new_ext == 1)].index
        if len(tgt) and len(pool):
            zt = z.loc[tgt[-1]].fillna(0).to_numpy()
            dist = np.sqrt(((z.loc[pool].fillna(0).to_numpy() - zt) ** 2).sum(axis=1))
            j = pool[int(np.argmin(dist))]
            all_d = np.sqrt(((z.fillna(0).to_numpy() - zt) ** 2).sum(axis=1))
            rep = {"deteriorating_transition_challenge": int(tgt[-1]), "nearest_clean_trend_success": int(j), "distance": float(dist.min()),
                   "distance_percentile_vs_all_challenges": float((all_d < dist.min()).mean()),
                   "features": {f: {"deteriorating": float(e1.loc[tgt[-1], f]), "clean_success": float(e1.loc[j, f])} for f in REP_FEATURES}}
            pd.DataFrame(rep["features"]).T.to_csv(CASES / "REPRESENTATION_CHECK.csv")
    pd.Series({k: v for k, v in rep.items() if k != "features"}).to_csv(CASES / "REPRESENTATION_CHECK_SUMMARY.csv")
    print(cases.groupby("case").size())
    print({k: v for k, v in rep.items() if k != "features"})


if __name__ == "__main__":
    main()
