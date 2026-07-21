"""NQ 1m Sequential Regime Health & Telemetry Study (phase-gated).

PHASE 1 (this file, run first): raw telemetry calibration. Compute 5 direction-
normalized per-bar telemetry features on every active regime bar (1..30) from the
existing transition capsule, then decile each on IS (2021-24) and measure LOCAL
forward outcomes (next-3-bar expansion %, next-3-bar opposite-flip %, next-5-bar
MFE/MAE). FALSIFICATION GATE 1: if the features do not sort these outcomes
monotonically, the branch is dead and Phases 2-4 are not built.

    python studies/regime_dna_knn/regime_health_telemetry.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")
IS_YEARS = [2021, 2022, 2023, 2024]
MAXBAR = 30


def build_matrices(df):
    n_post = df["n_post"].values.astype(int)
    N = len(df)
    B = int(min(MAXBAR + 2, max(n_post.max(), 1) + 1))
    H = np.full((N, B), np.nan); L = np.full((N, B), np.nan)
    C = np.full((N, B), np.nan); O = np.full((N, B), np.nan)
    H[:, 0] = df["flip_h"].values; L[:, 0] = df["flip_l"].values
    C[:, 0] = df["flip_c"].values; O[:, 0] = df["flip_o"].values
    ph = df["post_h"].tolist(); pl = df["post_l"].tolist()
    pc = df["post_c"].tolist(); po = df["post_o"].tolist()
    for i in range(N):
        k = min(n_post[i], B - 1)
        if k > 0:
            H[i, 1:k + 1] = ph[i][:k]; L[i, 1:k + 1] = pl[i][:k]
            C[i, 1:k + 1] = pc[i][:k]; O[i, 1:k + 1] = po[i][:k]
    return H, L, C, O, n_post


def telemetry_rows(df):
    H, L, C, O, n_post = build_matrices(df)
    d = df["direction"].values.astype(float)
    atr = df["atr_base"].values.astype(float)
    fo = df["flip_o"].values.astype(float)
    year = df["year"].values
    rid = df["regime_id"].values
    N = len(df)
    # direction-normalized signed extreme series: higher = more favorable
    ext = np.where(d[:, None] == 1, H, -L)            # favorable extreme per bar
    fav_close = (C - fo[:, None]) * d[:, None]          # favorable close excursion (pts)
    fo_ext = np.where(d == 1, fo, -fo)                  # flip-open as signed extreme

    rows = []
    for t in range(1, MAXBAR + 1):
        active = n_post > t                            # bar t is a regime bar (reversal is bar n_post)
        if not active.any():
            break
        idx = np.where(active)[0]
        # extreme through bar t (incl flip bar col 0)
        ext_run = np.fmax(fo_ext[idx], np.nanmax(ext[idx, 1:t + 1], axis=1))
        peak_fav = (ext_run - fo_ext[idx]) / atr[idx]   # peak favorable excursion through t (ATR)
        close_exc = fav_close[idx, t] / atr[idx]
        pullback = np.maximum(0.0, peak_fav - close_exc)
        # consecutive non-continuation (no new extreme) ending at t
        newhigh = np.zeros((len(idx), t), dtype=bool)
        runmax = fo_ext[idx].copy()
        for j in range(1, t + 1):
            e = ext[idx, j]
            newhigh[:, j - 1] = e > runmax + 1e-9
            runmax = np.fmax(runmax, e)
        stall = np.zeros(len(idx), dtype=int)
        for j in range(t - 1, -1, -1):
            cont = newhigh[:, j]
            stall = np.where(cont, stall, np.where(stall == (t - 1 - j), stall + 1, stall))
        # simpler consecutive-from-end:
        stall = np.zeros(len(idx), dtype=int)
        for j in range(t - 1, -1, -1):
            still = (stall == (t - 1 - j))
            stall = np.where(still & ~newhigh[:, j], stall + 1, stall)
        # progress efficiency through t
        rets = np.abs(np.diff(C[idx, :t + 1], axis=1))
        path = np.nansum(rets, axis=1)
        pnl = fav_close[idx, t]
        eff = np.where(path > 1e-9, pnl / path, 0.0)
        dist = fav_close[idx, t] / atr[idx]
        # ---- forward outcomes ----
        # next-3-bar expansion: new extreme in bars t+1..t+3
        hi3 = np.where(d[idx] == 1, np.nanmax(H[idx, t + 1:t + 4], axis=1),
                       -np.nanmax(-L[idx, t + 1:t + 4], axis=1)) if t + 1 < H.shape[1] else np.full(len(idx), np.nan)
        exp3 = (np.where(d[idx] == 1, hi3, hi3) > ext_run).astype(float)
        exp3 = np.where(np.isnan(hi3), np.nan, exp3)
        # next-3-bar opposite flip: reversal bar (n_post) within t+1..t+3
        flip3 = ((n_post[idx] - t) <= 3).astype(float)
        # next-5-bar MFE/MAE from close_t
        ct = C[idx, t]
        sl = slice(t + 1, t + 6)
        if t + 1 < H.shape[1]:
            mh = np.nanmax(H[idx, sl], axis=1); ml = np.nanmin(L[idx, sl], axis=1)
            mfe5 = np.where(d[idx] == 1, mh - ct, ct - ml) / atr[idx]
            mae5 = np.where(d[idx] == 1, ct - ml, mh - ct) / atr[idx]
            mfe5 = np.maximum(np.nan_to_num(mfe5, nan=np.nan), 0.0)
            mae5 = np.maximum(np.nan_to_num(mae5, nan=np.nan), 0.0)
        else:
            mfe5 = np.full(len(idx), np.nan); mae5 = np.full(len(idx), np.nan)
        sub = pd.DataFrame(dict(regime_id=rid[idx], year=year[idx], bar_index=t,
                                current_pullback_from_peak=pullback,
                                consecutive_non_continuation_bars=stall,
                                progress_efficiency_so_far=eff,
                                distance_from_flip_open=dist,
                                fwd3_expansion=exp3, fwd3_oppflip=flip3,
                                fwd5_mfe=mfe5, fwd5_mae=mae5))
        rows.append(sub)
    return pd.concat(rows, ignore_index=True)


FEATS = ["bar_index", "current_pullback_from_peak", "consecutive_non_continuation_bars",
         "progress_efficiency_so_far", "distance_from_flip_open"]


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    print(f"Capsule {len(cap):,} regimes. Building per-bar telemetry...")
    tele = telemetry_rows(cap)
    is_t = tele[tele.year.isin(IS_YEARS)].copy()
    print(f"Per-bar rows: {len(tele):,} (IS {len(is_t):,})")

    L = ["# Telemetry Calibration — Phase 1 (raw features, IS 2021–2024)", "",
         "Each raw telemetry feature is decile-sorted on IS; we report the LOCAL forward outcomes "
         "(next-3-bar new-extreme %, next-3-bar opposite-flip %, next-5-bar MFE/MAE in ATR). "
         "GATE 1: a feature is informative only if it sorts an outcome MONOTONICALLY "
         "(|Spearman(decile, outcome)| high) across deciles.", ""]
    gate_rows = []
    for f in FEATS:
        s = is_t[[f, "fwd3_expansion", "fwd3_oppflip", "fwd5_mfe", "fwd5_mae"]].dropna()
        if s[f].nunique() < 5:
            continue
        try:
            s["dec"] = pd.qcut(s[f], 10, labels=False, duplicates="drop") + 1
        except Exception:
            s["dec"] = s[f].rank(method="first").pipe(lambda r: pd.qcut(r, 10, labels=False, duplicates="drop")) + 1
        g = s.groupby("dec").agg(n=(f, "size"), exp=("fwd3_expansion", "mean"),
                                 flip=("fwd3_oppflip", "mean"), mfe=("fwd5_mfe", "mean"),
                                 mae=("fwd5_mae", "mean"))
        rho_flip = spearmanr(g.index, g["flip"]).statistic
        rho_exp = spearmanr(g.index, g["exp"]).statistic
        rho_mae = spearmanr(g.index, g["mae"]).statistic
        gate_rows.append((f, rho_exp, rho_flip, rho_mae))
        L.append(f"## {f}  — Spearman(decile→): expansion {rho_exp:+.2f}, oppflip {rho_flip:+.2f}, "
                 f"MAE {rho_mae:+.2f}")
        L.append("| Decile | n | Next3 Expansion% | Next3 OppFlip% | Next5 MFE | Next5 MAE |")
        L.append("| --- | --- | --- | --- | --- | --- |")
        for dec, r in g.iterrows():
            L.append(f"| {int(dec)} | {int(r.n):,} | {r.exp*100:.0f}% | {r.flip*100:.0f}% | "
                     f"{r.mfe:.2f} | {r.mae:.2f} |")
        L.append("")
    # Gate 1 verdict: at least one feature must monotonically sort flip-risk OR expansion strongly
    strong = [(f, re, rf, rm) for (f, re, rf, rm) in gate_rows
              if max(abs(re), abs(rf), abs(rm)) >= 0.80]
    L.append("## GATE 1 verdict")
    if strong:
        L.append(f"> [!TIP]\n> **GATE 1 PASS.** {len(strong)} feature(s) sort a local outcome monotonically "
                 f"(|Spearman|>=0.80): " + ", ".join(f"{f}(max ρ {max(abs(re),abs(rf),abs(rm)):.2f})"
                                                      for f, re, rf, rm in strong)
                 + ". Proceed to Phase 2 (KNN component diagnostics) — but note monotonic LOCAL "
                 "calibration is necessary, not sufficient; Phase 3 Oracle is the real ceiling test.")
    else:
        L.append("> [!WARNING]\n> **GATE 1 FAIL — branch dead.** No raw telemetry feature sorts the local "
                 "forward outcomes monotonically (max |Spearman| < 0.80). The price-action telemetry has no "
                 "native signal; a KNN block would only smooth noise. Study stopped per spec.")
    (OUT / "telemetry_calibration.md").write_text("\n".join(L), encoding="utf-8")
    print("Wrote telemetry_calibration.md")
    print("GATE 1:", "PASS" if strong else "FAIL")
    for f, re, rf, rm in gate_rows:
        print(f"  {f:<36} exp ρ{re:+.2f} flip ρ{rf:+.2f} mae ρ{rm:+.2f}")


if __name__ == "__main__":
    main()
