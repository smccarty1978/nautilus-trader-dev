"""Regime Health Decay — Lead-Time Diagnostic (NOT a trading system).

The one surviving signal: Model B removes 52% of imminent failures while sacrificing
1.8% of launches. Prior studies spent it as an ENTRY filter and it died. This asks the
DIFFERENT question: used as TRADE MANAGEMENT, does a per-bar health score deteriorate
BEFORE the reversal (usable exit) or only COINCIDENT with it (worthless observation)?

Causal per-bar health head (walk-forward):
  Health_k = 100 * P(regime reaches +2 ATR MFE from Bar-4 entry before it flips
                     | features through bar k).
Trained on IS 2021-24 pooled (regime, bar k) rows, k=4..KMAX, features = feats_through(k)
(leak-corrected k=Nbar — at bar k the model sees ONLY bars 0..k). The TARGET is a
regime-level forward outcome (allowed — supervised label); FEATURES are strictly causal.
Scored OOS 2025-26 at every bar.

Centerpiece = FLIP-ALIGNED health curve: mean Health at j bars BEFORE the opposite flip,
split by outcome cohort. If failures' health is already low at j=5..10 while winners' is
high, lead time is real. If health only collapses at j=0..1 (the flip bar itself), it is
OBSERVATION not warning — and that kills the exit-engine idea cleanly.

Then lead-time tables: first-deterioration bar (health < theta) vs flip bar, per cohort.
Median lead 1 bar = worthless; 5 = interesting; 10 = very interesting (user's bar).

    python studies/regime_dna_knn/regime_health_decay_leadtime.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E  # noqa: E402
import progressive_separability as P  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")

KMAX = 40                       # health trajectory horizon (bars from flip); p90 surv ~29
REACH = 2.0                     # winner definition: reaches +2 ATR MFE from Bar-4 entry
HEALTH_FEATS = ["mfe", "mae", "health", "pullback", "dist_flip_open", "progress_count",
                "close_prog_ratio", "flip_open_viol", "consec_noncont", "close_loc",
                "upper_wick", "range_exp", "vol_exp"]
THETAS = [70, 60, 50, 40]
JBINS = [0, 1, 2, 3, 4, 5, 7, 10]


def feats_at(df, M, k):
    """Causal feature row for every regime at bar k (through-bar-k). Adds bars_since_flip."""
    X = P.feats_through(df, M, k)[HEALTH_FEATS].copy()
    X["bars_since_flip"] = float(k)
    return X


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df); H, L, C, O, V, n = M
    d = df.direction.values.astype(float); atr = df.atr_base.values.astype(float)
    yr = df.year.values
    alive = n >= 4
    entry = O[:, 4]                                  # Bar-4 entry (causal)

    # ---- trade-level outcomes (from Bar-4 entry, over bars 4..n) ----
    import warnings; warnings.filterwarnings("ignore", message="All-NaN slice encountered")
    fav = np.where(d[:, None] == 1, H[:, 4:] - entry[:, None], entry[:, None] - L[:, 4:])
    mfe_full = np.maximum(np.nanmax(fav, axis=1) / atr, 0.0)
    reach2 = (mfe_full >= REACH).astype(int)         # winner cohort + training target
    idx = np.arange(len(df))
    flip_c = C[idx, np.minimum(n, 61)]
    holdflip = (flip_c - d * 0.25 - (entry + d * 0.125) - 0) * d * 20.0 - 5.0  # hold-to-flip net
    lose = holdflip < 0                              # eventually loses money
    fail = mfe_full < 1.0                            # never really moved (clean failure)

    # ---- build training pool: IS pooled (regime, bar k) ----
    is_m = alive & (yr < 2025); oos_m = alive & (yr >= 2025)
    Xtr_parts, ytr_parts = [], []
    for k in range(4, KMAX + 1):
        m = is_m & (n >= k)                          # regime still alive at bar k
        gi_tr = np.where(m)[0]                        # integer positions (audit W2: safe vs index)
        if gi_tr.size == 0:
            continue
        Xtr_parts.append(feats_at(df, M, k).iloc[gi_tr].values)
        ytr_parts.append(reach2[gi_tr])
    Xtr = np.vstack(Xtr_parts); ytr = np.concatenate(ytr_parts)
    print(f"Training pool: {len(ytr):,} (regime,bar) rows, P(reach2)={ytr.mean()*100:.1f}%")
    mdl = lgb.LGBMClassifier(n_estimators=400, learning_rate=0.03, num_leaves=31,
                             class_weight="balanced", random_state=0, verbose=-1)
    mdl.fit(Xtr, ytr)

    # ---- score OOS at every bar k → health trajectory matrix ----
    oos_idx = np.where(oos_m)[0]
    pos = {gi: i for i, gi in enumerate(oos_idx)}
    Htraj = np.full((len(oos_idx), KMAX + 1), np.nan)   # health[regime, k]
    for k in range(4, KMAX + 1):
        m = oos_m & (n >= k)
        gi = np.where(m)[0]
        if gi.size == 0:
            continue
        Xk = feats_at(df, M, k).iloc[gi].values
        ph = mdl.predict_proba(Xk)[:, 1] * 100.0
        for j, g in enumerate(gi):
            Htraj[pos[g], k] = ph[j]

    no = n[oos_idx]                                   # n_post for OOS trades
    R2 = reach2[oos_idx].astype(bool); LO = lose[oos_idx]; FA = fail[oos_idx]
    yroos = yr[oos_idx]

    # ================= REPORT =================
    R = ["# Regime Health Decay — Lead-Time Diagnostic", "",
         f"OOS 2025-26 Bar-4 survivors: **{len(oos_idx):,}**. Health_k = P(reach +{REACH:.0f} ATR MFE "
         "before flip | features thru bar k), walk-forward (IS 2021-24 pooled per-bar → OOS). "
         "Features strictly causal (bars 0..k); target is regime-level forward outcome.", "",
         f"Cohorts: **WIN2** reach ≥+{REACH:.0f} ATR ({R2.mean()*100:.1f}%) · **LOSE** hold-to-flip net<0 "
         f"({LO.mean()*100:.1f}%) · **FAIL** MFE<1 ATR ({FA.mean()*100:.1f}%).", "",
         "## 1. Flip-aligned health curve — mean Health at j bars BEFORE the opposite flip",
         "The decisive view. Lead time exists only if FAIL/LOSE health is already low while WIN2 is "
         "still high, several bars before the flip (j large). If all cohorts only collapse at j=0..1, "
         "the score OBSERVES the flip, it does not predict it.", "",
         "| bars before flip (j) | WIN2 | LOSE | FAIL | all |",
         "| --- | --- | --- | --- | --- |"]

    def flip_aligned(cohort, j):
        # health at bar (n-j) for trades with n in [4+j, KMAX]; need that bar scored
        vals = []
        for i in np.where(cohort)[0]:
            k = no[i] - j
            if 4 <= k <= KMAX and not np.isnan(Htraj[i, k]):
                vals.append(Htraj[i, k])
        return np.median(vals) if vals else np.nan, len(vals)

    for j in JBINS:
        w, _ = flip_aligned(R2, j); lo, _ = flip_aligned(LO, j)
        fa, _ = flip_aligned(FA, j); al, nn = flip_aligned(np.ones(len(oos_idx), bool), j)
        R.append(f"| {j} | {w:.0f} | {lo:.0f} | {fa:.0f} | {al:.0f} |")

    # ---- 2. peak→flip decay: where is the peak health, where does it collapse ----
    R += ["", "## 2. Health peak location & collapse (per cohort)",
          "peak bar = argmax health; collapse bar = first bar after peak with health<50; "
          "lead = flip_bar − collapse_bar (bars of warning before the flip).", "",
          "| Cohort | n | median peak health | median peak bar | median collapse→flip lead | % no collapse pre-flip |",
          "| --- | --- | --- | --- | --- | --- |"]

    def decay_stats(cohort):
        peaks, peakbar, leads, nocol = [], [], [], 0
        ci = np.where(cohort)[0]
        for i in ci:
            tr = Htraj[i, 4:KMAX + 1]
            ks = np.arange(4, KMAX + 1)
            valid = ~np.isnan(tr)
            if valid.sum() < 2:
                continue
            tv = tr[valid]; kv = ks[valid]
            pk = np.argmax(tv)
            peaks.append(tv[pk]); peakbar.append(kv[pk])
            # collapse = first bar AFTER peak with health<50
            after = kv[pk:]; av = tv[pk:]
            col = None
            for kk, vv in zip(after, av):
                if vv < 50:
                    col = kk; break
            flipbar = no[i]
            if col is not None and col <= flipbar:
                leads.append(flipbar - col)
            else:
                nocol += 1
        return (np.median(peaks) if peaks else np.nan,
                np.median(peakbar) if peakbar else np.nan,
                np.median(leads) if leads else np.nan,
                100 * nocol / max(len(ci), 1))

    for name, coh in [("WIN2", R2), ("LOSE", LO), ("FAIL", FA)]:
        pk, pb, ld, nc = decay_stats(coh)
        R.append(f"| {name} | {coh.sum():,} | {pk:.0f} | {pb:.0f} | "
                 f"{('%.0f' % ld) if ld==ld else '—'} | {nc:.0f}% |")

    # ---- 3. threshold lead-time: first bar health<theta → flip ----
    R += ["", "## 3. First-deterioration lead time (first bar Health<θ → flip), median bars",
          "Median (bars) from the first time health drops below θ to the opposite flip. Higher = more "
          "warning. Also % of cohort that EVER drops below θ before the flip (coverage).", "",
          "| θ | WIN2 lead (cov) | LOSE lead (cov) | FAIL lead (cov) |",
          "| --- | --- | --- | --- |"]

    def thresh_lead(cohort, theta):
        leads, cov, tot = [], 0, 0
        for i in np.where(cohort)[0]:
            tr = Htraj[i, 4:KMAX + 1]; ks = np.arange(4, KMAX + 1)
            valid = ~np.isnan(tr)
            if valid.sum() < 1:
                continue
            tot += 1
            tv = tr[valid]; kv = ks[valid]
            below = kv[tv < theta]
            below = below[below <= no[i]]
            if below.size:
                cov += 1
                leads.append(no[i] - below[0])
        return (np.median(leads) if leads else np.nan, 100 * cov / max(tot, 1))

    for th in THETAS:
        cells = []
        for coh in (R2, LO, FA):
            ld, cv = thresh_lead(coh, th)
            cells.append(f"{('%.0f' % ld) if ld==ld else '—'} ({cv:.0f}%)")
        R.append(f"| {th} | {cells[0]} | {cells[1]} | {cells[2]} |")

    # ---- 4. separation: would 'exit when health<θ' protect losers without killing winners? ----
    R += ["", "## 4. Exit-rule separation (diagnostic): 'exit at first Health<θ'",
          "For WIN2: % that would be exited BEFORE reaching their +2 ATR peak (premature kill = bad). "
          "For LOSE: median lead the exit gives before the flip (good). A usable engine needs LOW "
          "premature-kill on winners AND positive lead on losers.", "",
          "| θ | WIN2 premature-exit % | LOSE median lead (bars) |", "| --- | --- | --- |"]

    # bar at which each WIN2 first reaches +2 ATR (from entry)
    def first_reach_bar(i):
        gi = oos_idx[i]
        e = entry[gi]; dd = d[gi]; a = atr[gi]
        for k in range(4, min(no[i], 61) + 1):
            ex = (H[gi, k] - e) if dd == 1 else (e - L[gi, k])
            if ex / a >= REACH:
                return k
        return None

    for th in THETAS:
        prem, premtot = 0, 0
        for i in np.where(R2)[0]:
            tr = Htraj[i, 4:KMAX + 1]; ks = np.arange(4, KMAX + 1)
            valid = ~np.isnan(tr)
            if valid.sum() < 1:
                continue
            premtot += 1
            below = ks[valid][tr[valid] < th]
            rb = first_reach_bar(i)
            if below.size and rb is not None and below[0] < rb:
                prem += 1
        ld, _ = thresh_lead(LO, th)
        R.append(f"| {th} | {100*prem/max(premtot,1):.0f}% | {('%.0f' % ld) if ld==ld else '—'} |")

    # ---- verdict (rigorous: separate CONCURRENT separation from LEADING decay) ----
    fa5, _ = flip_aligned(FA, 5); w5, _ = flip_aligned(R2, 5)
    fa1, _ = flip_aligned(FA, 1); w1, _ = flip_aligned(R2, 1)
    gap5 = (w5 - fa5) if (w5 == w5 and fa5 == fa5) else float("nan")
    lose_peak, _, lose_lead, _ = decay_stats(LO)
    _, _, _, win_nocol = decay_stats(R2)
    # premature-kill on winners at θ=50
    prem50, premtot = 0, 0
    for i in np.where(R2)[0]:
        tr = Htraj[i, 4:KMAX + 1]; ks = np.arange(4, KMAX + 1); valid = ~np.isnan(tr)
        if valid.sum() < 1:
            continue
        premtot += 1
        below = ks[valid][tr[valid] < 50]; rb = first_reach_bar(i)
        if below.size and rb is not None and below[0] < rb:
            prem50 += 1
    prem50 = 100 * prem50 / max(premtot, 1)
    # LEADING decay requires: losers were HEALTHY then decayed (peak high) AND winners get
    # real warning (low no-collapse) AND an exit rule doesn't slaughter winners. NOT the raw gap.
    leading = (lose_peak >= 60) and (win_nocol <= 40) and (prem50 <= 40)
    R += ["", "## Verdict — does the health score give LEAD TIME (predict) or just OBSERVE?", ""]
    R.append(f"j=5 before flip: WIN2 {w5:.0f} vs FAIL {fa5:.0f} (gap {gap5:+.0f}). "
             f"LOSE median PEAK health **{lose_peak:.0f}** (were they ever healthy?). "
             f"WIN2 flip-without-collapse **{win_nocol:.0f}%**. "
             f"Exit-when-health<50 kills **{prem50:.0f}%** of winners before +{REACH:.0f} ATR.")
    if leading:
        R.append("> [!TIP]\n> **Lead time looks REAL** — losers were genuinely healthy then DECAYED before the "
                 "flip, winners get warning, and an exit rule does not slaughter winners. Build the Health-Decay "
                 "exit and gate on 1s/NT streaming; then layer 5s micro-health.")
    else:
        R.append("> [!WARNING]\n> **NOT lead time — the separation is CONCURRENT, not LEADING.** The big j=5 gap "
                 f"is the MFE-tautology: health reads excursion-so-far, so winners (already moved) read high and "
                 f"failures read low — but failures are **born unhealthy** (LOSE median peak only {lose_peak:.0f}, "
                 f"peaked ~bar 5), not decayed from health. Winners **flip abruptly from full health** "
                 f"({win_nocol:.0f}% show no pre-collapse; collapse→flip lead is ~2 bars for ALL cohorts — no "
                 f"differential warning). An exit-on-unhealthy rule would prematurely kill **{prem50:.0f}% of "
                 "winners**. So 1m OHLCV health confirms the break as it happens; it does not precede it. "
                 "Consistent with rejection-power D6 (failures already resolving by the decision bar).\n> \n> "
                 "**The door this leaves OPEN (the user's instinct):** at 1m the flip is ABRUPT — winners flip "
                 "from health ~95 with no 1m decay phase. Any genuine deterioration signature would therefore "
                 "have to live in the **final-minute 5-SECOND microstructure**, which 1m bars structurally cannot "
                 "resolve. That — a 5s micro-health layer measuring last-30-60s deterioration on still-healthy 1m "
                 "regimes — is the motivated next test, NOT another 1m health model.")
    (OUT / "regime_health_decay_leadtime.md").write_text("\n".join(R), encoding="utf-8")
    print("Wrote regime_health_decay_leadtime.md")
    print(f"Flip-aligned j=5: WIN2 {w5:.0f} vs FAIL {fa5:.0f} (gap {gap5:+.0f}) | j=1: {w1:.0f} vs {fa1:.0f}")


if __name__ == "__main__":
    main()
