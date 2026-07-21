"""Post-Bar3 Survivor Opportunity After Quick-Failure Rejection.

Model B (features through Bar 3) is used ONLY as a rejection filter, not a trading
system. Population = regimes ALIVE at Bar 3 (n_post >= 4, so Bar 4 exists for entry
and the regime did not terminate by Bar 3). Among survivors a QuickFailure is exactly
npost==4 (flips at the entry bar) — these are the losers the filter targets.

Pipeline (walk-forward, leak-aware):
  1. Train Model B QuickFailure head on IS survivors (2021-24, n>=4), score OOS
     survivors (2025-26, n>=4). feats_through(Nbar=3) → MODEL_B columns only.
     Features use ONLY bars 0..3 (k=Nbar, leak-corrected); entry is at Bar 4 OPEN,
     strictly after the feature window — clean causal separation.
  2. Rank OOS survivors by P(QuickFail) descending; reject worst 10/20/30/40/50%.
  3. For each retained population, measured from Bar 4 entry, report composition,
     remaining MFE/MAE (avg/median/p75, ATR-norm), 4 barrier-touch probabilities,
     and net $/trade for fixed brackets / hold-to-flip / bar10 exit.
  4. Compare every retained population vs the no-filter Bar3-survivor baseline.

Costs: $20/pt, $5 RT commission, 0.5t entry slippage, 1.0t exit slippage. PT fills as
a resting LIMIT at pt_px exactly (no favorable slippage); SL fills market at sl_px with
adverse slippage. Same-bar PT+SL ambiguity resolves ADVERSE-FIRST (conservative).

CAVEAT (memory: bar_mode_overstates_fade_strategies / be_simulation_path_checkpoint):
barrier-touch and bracket net$ are computed on 1m bars, which OVERSTATE barrier-touch
edge vs 1s/tick. These numbers are a DIRECTIONAL SCREEN, not a deployment claim. If any
retained population looks monetizable here, it requires 1s/tick re-validation.

    python studies/regime_dna_knn/post_bar3_survivor_opportunity.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import early_health_filter as E      # noqa: E402  (compute_labels_features)
import progressive_separability as P  # noqa: E402  (build, feats_through, PRE5)
from rejection_power import MODEL_B, gbm  # noqa: E402
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path("studies/regime_dna_knn/results")

MULT = 20.0
TICK = 0.25
COMM = 5.0
ENTRY = 0.5 * TICK   # entry slippage (adverse)
EXIT = 1.0 * TICK    # exit slippage (adverse, on market exits)
ENTRY_BAR = 4        # enter at the OPEN of the 4th post-flip bar
BMAX = 61            # matrix column cap (build uses B=62)
REJECT = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50]
# (PT, SL) ATR brackets, matched to the 4 barrier-probability rows
BRACKETS = [(0.5, 0.5), (1.0, 0.5), (1.5, 0.75), (2.0, 1.0)]


def barrier_first_touch(entry, d, atr, H, L, n, pt, sl):
    """First-touch outcome walking bars ENTRY_BAR..n. Returns +1 (PT first), -1 (SL
    first), 0 (neither by regime end). Same-bar PT+SL → SL first (conservative).
    Anchors PT/SL to the fill price (entry + entry slip) so touch probs match the
    exact bracket levels used in bracket_pnl (audit W1)."""
    N = len(entry)
    fill = entry + d * ENTRY
    pt_px = fill + d * pt * atr
    sl_px = fill - d * sl * atr
    out = np.zeros(N, dtype=np.int8)
    resolved = np.zeros(N, dtype=bool)
    last = np.minimum(n, BMAX)
    for j in range(ENTRY_BAR, BMAX + 1):
        active = (~resolved) & (j <= last)
        if not active.any():
            continue
        hj = H[:, j]; lj = L[:, j]
        sl_hit = np.where(d == 1, lj <= sl_px, hj >= sl_px) & active & ~np.isnan(hj)
        pt_hit = np.where(d == 1, hj >= pt_px, lj <= pt_px) & active & ~np.isnan(hj)
        # adverse first on same-bar ambiguity
        out[sl_hit] = -1
        pt_only = pt_hit & ~sl_hit
        out[pt_only] = 1
        resolved |= (sl_hit | pt_only)
    return out


def bracket_pnl(entry_raw, d, atr, H, L, C, n, pt, sl):
    """Net $/trade for a fixed (pt,sl) bracket. PT = limit fill at pt_px (no favorable
    slip); SL = market fill at sl_px - adverse slip; neither = flip-close - adverse slip."""
    N = len(entry_raw)
    fill = entry_raw + d * ENTRY
    pt_px = fill + d * pt * atr
    sl_px = fill - d * sl * atr
    exit_px = np.full(N, np.nan)
    resolved = np.zeros(N, dtype=bool)
    last = np.minimum(n, BMAX)
    for j in range(ENTRY_BAR, BMAX + 1):
        active = (~resolved) & (j <= last)
        if not active.any():
            continue
        hj = H[:, j]; lj = L[:, j]
        sl_hit = np.where(d == 1, lj <= sl_px, hj >= sl_px) & active & ~np.isnan(hj)
        pt_hit = np.where(d == 1, hj >= pt_px, lj <= pt_px) & active & ~np.isnan(hj)
        exit_px[sl_hit] = (sl_px - d * EXIT)[sl_hit]
        pt_only = pt_hit & ~sl_hit
        exit_px[pt_only] = pt_px[pt_only]            # limit fill, no slippage
        resolved |= (sl_hit | pt_only)
    # unresolved → exit at flip (last bar close), adverse slip
    idx = np.arange(N)
    flip_c = C[idx, last]
    unres = ~resolved
    exit_px[unres] = (flip_c - d * EXIT)[unres]
    return (exit_px - fill) * d * MULT - COMM


def close_exit_pnl(entry_raw, d, C, n, exit_bar_cap):
    """Exit at the close of bar min(n, cap), adverse slip. exit_bar_cap=10 → bar10
    exit; cap=BMAX → hold-to-flip (terminal opposite-flip bar close)."""
    idx = np.arange(len(entry_raw))
    last = np.minimum(n, exit_bar_cap)
    fill = entry_raw + d * ENTRY
    ex = C[idx, last] - d * EXIT
    return (ex - fill) * d * MULT - COMM


def pct(a):
    return np.array([np.mean(a), np.median(a), np.percentile(a, 75)])


def fmt_money(x):
    return f"${x:+,.2f}"


def main():
    cap = pd.read_parquet(OUT / "early_health_capsule.parquet")
    df = E.compute_labels_features(cap).reset_index(drop=True)
    M = P.build(df)
    H, L, C, O, V, n = M
    d = df.direction.values.astype(float)
    atr = df.atr_base.values.astype(float)
    yr = df.year.values
    lab = df.label.values

    # Model B features through Bar 3 (leak-corrected, k=Nbar=3)
    XB = P.feats_through(df, M, 3)[MODEL_B].values

    # Population: ALIVE at Bar 3 = n_post >= ENTRY_BAR (Bar 4 exists; regime not done by Bar 3)
    alive = n >= ENTRY_BAR
    is_m = alive & (yr < 2025)
    oos_m = alive & (yr >= 2025)
    yQ = (lab == "QuickFailure").astype(int)   # among survivors, == npost4

    # Train QF head on IS survivors, score OOS survivors (walk-forward, no OOS tuning)
    pQ = gbm(XB[is_m], yQ[is_m], XB[oos_m])    # P(QuickFail) risk on OOS survivors

    # Restrict every array to the OOS survivor pool
    gi = np.where(oos_m)[0]
    dd = d[gi]; aa = atr[gi]; nn = n[gi]; ll = lab[gi]; yy = yr[gi]
    Hs, Ls, Cs = H[gi], L[gi], C[gi]
    entry_raw = O[gi, ENTRY_BAR]               # Bar 4 open = causal entry price

    # Remaining MFE/MAE from Bar 4 entry over bars 4..n (ATR-norm), forward opportunity
    fav = np.where(dd[:, None] == 1, Hs[:, ENTRY_BAR:] - entry_raw[:, None],
                   entry_raw[:, None] - Ls[:, ENTRY_BAR:])
    adv = np.where(dd[:, None] == 1, entry_raw[:, None] - Ls[:, ENTRY_BAR:],
                   Hs[:, ENTRY_BAR:] - entry_raw[:, None])
    import warnings
    warnings.filterwarnings("ignore", message="All-NaN slice encountered")
    rem_mfe = np.maximum(np.nanmax(fav, axis=1) / aa, 0.0)
    rem_mae = np.maximum(np.nanmax(adv, axis=1) / aa, 0.0)

    # Pre-compute outcome arrays once on the full OOS survivor pool
    barr = {br: barrier_first_touch(entry_raw, dd, aa, Hs, Ls, nn, br[0], br[1]) for br in BRACKETS}
    brk_pnl = {br: bracket_pnl(entry_raw, dd, aa, Hs, Ls, Cs, nn, br[0], br[1]) for br in BRACKETS}
    flip_pnl = close_exit_pnl(entry_raw, dd, Cs, nn, BMAX)
    bar10_pnl = close_exit_pnl(entry_raw, dd, Cs, nn, 10)

    # Rank by QF risk (descending); reject worst X%
    order = np.argsort(-pQ)                     # worst (highest QF risk) first
    Ntot = len(pQ)

    R = ["# Post-Bar3 Survivor Opportunity After Quick-Failure Rejection", "",
         f"OOS 2025-26 survivors (alive at Bar 3, n_post≥{ENTRY_BAR}): **{Ntot:,}** regimes. "
         "Model B (features thru Bar 3, leak-corrected k=Nbar) QuickFailure head trained on IS "
         "2021-24 survivors, scored OOS. Reject the worst-X% by P(QuickFail); enter survivors at "
         "**Bar 4 open** (causal — features end Bar 3, entry Bar 4).", "",
         "> [!CAUTION]\n> Barrier-touch probabilities and bracket net$ are 1m-bar resolution, which "
         "**OVERSTATES** barrier edge vs 1s/tick (memory: bar-mode overstates fade/touch strategies "
         "$15-25K/yr; BE/path checkpoints inflate $14K). Treat as a DIRECTIONAL SCREEN. Net$ also "
         "split by year below — a single pooled positive is not a monetizability verdict.", "",
         "Costs: $20/pt, $5 RT, 0.5t entry slip, 1.0t exit slip. PT = limit fill at pt_px (no "
         "favorable slip); SL = market at sl_px − slip; same-bar PT+SL → SL first (conservative).", "",
         "> [!NOTE]\n> The model is walk-forward (trained IS-only), but the \"reject worst X%\" cut is an "
         "**OOS-rank-relative** percentile — inherent to a reject-worst-X% framing (you need the population "
         "to take a fraction of it). It is NOT an IS-derived pQ threshold, so \"reject worst 20%\" is not a "
         "portable deployment rule; a deployment gate would fix θ from the IS score distribution.", ""]

    # ---- Table 1: composition + remaining MFE/MAE ----
    R += ["## Step 2a — Composition & remaining MFE/MAE (from Bar 4 entry, ATR-norm)", "",
          "| Reject worst | n | Launch% | QuickFail% | Chop% | MFE avg/med/p75 | MAE avg/med/p75 |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    pops = {}
    for q in REJECT:
        k = int(Ntot * q)
        keep = np.sort(order[k:])               # retained indices (into OOS pool)
        pops[q] = keep
        lk = ll[keep]
        mfe = pct(rem_mfe[keep]); mae = pct(rem_mae[keep])
        tag = "baseline (none)" if q == 0 else f"worst {int(q*100)}%"
        R.append(f"| {tag} | {len(keep):,} | {(lk=='TradableLaunch').mean()*100:.1f}% | "
                 f"{(lk=='QuickFailure').mean()*100:.1f}% | {(lk=='ChaoticChop').mean()*100:.1f}% | "
                 f"{mfe[0]:.2f}/{mfe[1]:.2f}/{mfe[2]:.2f} | {mae[0]:.2f}/{mae[1]:.2f}/{mae[2]:.2f} |")

    # ---- Table 2: barrier-touch probabilities ----
    R += ["", "## Step 2b — Barrier-touch probabilities P(PT before SL) [1m-bar, overstated]", "",
          "| Reject worst | +0.5/−0.5 | +1.0/−0.5 | +1.5/−0.75 | +2.0/−1.0 |",
          "| --- | --- | --- | --- | --- |"]
    for q in REJECT:
        keep = pops[q]
        cells = []
        for br in BRACKETS:
            o = barr[br][keep]
            cells.append(f"{(o == 1).mean()*100:.1f}%")
        tag = "baseline (none)" if q == 0 else f"worst {int(q*100)}%"
        R.append(f"| {tag} | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} |")

    # ---- Table 3: net $/trade (pooled OOS) ----
    R += ["", "## Step 2c — Net $/trade (pooled OOS) [1m-bar, overstated]", "",
          "| Reject worst | B 0.5/0.5 | B 1.0/0.5 | B 1.5/0.75 | B 2.0/1.0 | Hold-to-flip | Bar10 exit |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    for q in REJECT:
        keep = pops[q]
        bcells = [fmt_money(brk_pnl[br][keep].mean()) for br in BRACKETS]
        tag = "baseline (none)" if q == 0 else f"worst {int(q*100)}%"
        R.append(f"| {tag} | {bcells[0]} | {bcells[1]} | {bcells[2]} | {bcells[3]} | "
                 f"{fmt_money(flip_pnl[keep].mean())} | {fmt_money(bar10_pnl[keep].mean())} |")

    # ---- Table 4: year-split robustness for the headline exit policies ----
    R += ["", "## Step 2d — Year split (net $/trade), best bracket + hold-to-flip + bar10", "",
          "A policy is monetizable only if net-positive in BOTH 2025 and 2026 (per methodology).", "",
          "| Reject worst | B 1.5/0.75 25 | 26 | Hold-flip 25 | 26 | Bar10 25 | 26 |",
          "| --- | --- | --- | --- | --- | --- | --- |"]
    br_h = (1.5, 0.75)
    for q in REJECT:
        keep = pops[q]
        ykeep = yy[keep]
        def ys(arr):
            a = arr[keep]
            return a[ykeep == 2025].mean(), a[ykeep == 2026].mean()
        b25, b26 = ys(brk_pnl[br_h]); f25, f26 = ys(flip_pnl); t25, t26 = ys(bar10_pnl)
        tag = "baseline (none)" if q == 0 else f"worst {int(q*100)}%"
        R.append(f"| {tag} | {fmt_money(b25)} | {fmt_money(b26)} | {fmt_money(f25)} | "
                 f"{fmt_money(f26)} | {fmt_money(t25)} | {fmt_money(t26)} |")

    # ---- Verdict (monetizability, not composition) ----
    # Scan every retained pop × every exit policy for net-positive in BOTH years.
    policies = {f"B {br[0]}/{br[1]}": brk_pnl[br] for br in BRACKETS}
    policies["Hold-to-flip"] = flip_pnl
    policies["Bar10"] = bar10_pnl
    winners = []
    for q in REJECT:
        keep = pops[q]; ykeep = yy[keep]
        for pname, arr in policies.items():
            a = arr[keep]
            n25 = a[ykeep == 2025].mean(); n26 = a[ykeep == 2026].mean()
            if n25 > 0 and n26 > 0:
                winners.append((q, pname, a.mean(), n25, n26))

    base_keep = pops[0.0]
    base_best = max(policies.items(), key=lambda kv: kv[1][base_keep].mean())
    R += ["", "## Verdict — is the surviving population monetizable?", ""]
    if winners:
        R.append("> [!TIP]\n> **Candidate(s) net-positive in BOTH years (1m-bar):**")
        for q, pname, mn, a25, a26 in sorted(winners, key=lambda w: -w[2]):
            R.append(f"> - reject worst {int(q*100)}% + **{pname}** → pooled {fmt_money(mn)}/tr "
                     f"(2025 {fmt_money(a25)}, 2026 {fmt_money(a26)})")
        R.append("> \n> ⚠️ All on 1m-bar resolution (overstated). REQUIRES 1s/tick re-validation "
                 "before any monetizability claim — bar-mode flatters barrier-touch exits.")
    else:
        R.append("> [!WARNING]\n> **NO — rejecting predicted QuickFailures does NOT create a monetizable "
                 "Bar-4 entry universe.** No retained population × exit policy is net-positive in BOTH "
                 "2025 and 2026, even at 1m-bar resolution (which OVERSTATES barrier edge). Composition "
                 "improves (QuickFail% falls, MFE/MAE tilt up) but the surviving population's forward "
                 "opportunity does not clear costs. The rejection power is real but **not monetizable** as "
                 "a Bar-4 entry gate — consistent with it being an exit/management signal, not an entry "
                 "edge (rejection_power.md D6).")
    R.append("")
    R.append(f"Baseline (no filter) best policy: **{base_best[0]}** at "
             f"{fmt_money(base_best[1][base_keep].mean())}/tr pooled OOS.")

    (OUT / "post_bar3_survivor_opportunity.md").write_text("\n".join(R), encoding="utf-8")
    print(f"Wrote post_bar3_survivor_opportunity.md")
    print(f"OOS survivors: {Ntot:,} | both-year-positive candidates: {len(winners)}")
    for q, pname, mn, a25, a26 in sorted(winners, key=lambda w: -w[2])[:5]:
        print(f"  reject {int(q*100)}% + {pname}: {mn:+.2f}/tr (25 {a25:+.2f}, 26 {a26:+.2f})")


if __name__ == "__main__":
    main()
