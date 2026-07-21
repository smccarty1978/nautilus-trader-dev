"""Trend Quality Emergence Curve.

For regime state snapshots at bars 4/6/8/10/12/15/20, answer:
  A. When does hC become predictive of runner/bad outcomes?
  B. How much MFE opportunity remains at each age?
  C. Which pullback state (Healthy/HH-HardStall/MH-HardStall/LH-HardStall/DETER) has
     the best remaining expectancy, reignition odds, and flip risk?
  D. Does delayed entry (bar 8/12/15/first-HH-HardStall) improve economics vs bar-4?
  E. 5-point conclusion on whether trend-quality is monetizable after costs.

Conventions:
  - "Bar k" = column index k in OHLCV matrices (bar 0 = flip bar, bar 4 = 4th post-flip bar)
  - Age entries: enter at O[:,k] open (decided at bar k-1 close) — no state conditioning
  - State entries: enter at O[:,k_state+1] open (decided at bar k_state close, when state known)
  - All simulations: 1-lot, bar-mode, $4.06 commission/RT, $20/pt NQ
  - OOS: 2025+2026 separate; IS thresholds always from year<2025 data

Bar-mode overstatement caveat: ~$9-18/tr vs tick-mode on this signal class.
Treat as opportunity-landscape mapping, not deployment-grade claim.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backtests" / "studies" / "regime_dna_knn"))
sys.path.insert(0, str(ROOT))

import early_health_filter as E       # noqa: E402
import progressive_separability as P  # noqa: E402

KNN_DIR = ROOT / "backtests/studies/regime_dna_knn/results"
OUT     = ROOT / "collectors/collector_v2/results/combined_arch"

AGES   = [4, 6, 8, 10, 12, 15, 20]
OOS    = [2025, 2026]
MULT   = 20.0   # NQ $20/pt
COMM   = 4.06   # commission per round-trip, 1 lot

STATE_ORDER = ["Healthy", "HH-HardStall", "MH-HardStall", "LH-HardStall", "DETER"]

# ─────────────────────────────────────────────────────────────────────────────
# 1. Load capsule + OHLCV matrices
# ─────────────────────────────────────────────────────────────────────────────
print("Loading capsule ...")
cap = pd.read_parquet(KNN_DIR / "early_health_capsule.parquet")
df  = E.compute_labels_features(cap).reset_index(drop=True)
M   = P.build(df)
H, L, C, O, V, _n = M

d     = df.direction.values.astype(float)          # +1 long / -1 short
atr   = df.atr_base.values.astype(float)
npost = df.n_post.values.astype(int)
ts    = df.regime_start_ts.astype("int64").values
year  = df.year.values.astype(int)
N     = len(df)
NCOL  = O.shape[1]  # 62

# Bar-4 entry (baseline)
entry4  = O[:, 4]
term    = np.minimum(npost, 61)
exitpx4 = C[np.arange(N), term]
pnl4    = (exitpx4 - entry4) * d * MULT - COMM      # 1-lot bar-mode $/trade

# Labels (from bar-4 entry perspective)
cols    = np.arange(NCOL)
fav_raw = np.where(d[:, None] == 1,                  # shape (N, NCOL)
                   H - entry4[:, None],
                   entry4[:, None] - L)
# favourable excursion in points; NaN beyond npost

# Aggregate helpers
def mfe_consumed_at(k: int) -> np.ndarray:
    """Max favourable excursion from bar-4 entry through bar k, in ATR."""
    m = (cols >= 4) & (cols <= k)
    arr = np.where(m[None, :], fav_raw, np.nan)
    return np.maximum(np.nan_to_num(np.nanmax(arr, axis=1), nan=0.0), 0.0) / atr

def mfe_remaining_after(k: int) -> np.ndarray:
    """Max favourable excursion from bar k+1 onward (to flip), in ATR."""
    m = cols > k
    arr = np.where(m[None, :], fav_raw, np.nan)
    return np.maximum(np.nan_to_num(np.nanmax(arr, axis=1), nan=0.0), 0.0) / atr

mfe_total = mfe_consumed_at(61)   # max over all bars 4..flip

# Outcome labels
pnl4_atr = (exitpx4 - entry4) * d / atr
mfe4_atr  = mfe_remaining_after(3)   # max from bar 4 onward (i.e. after entering)
runner = ((pnl4_atr >= 1.5) | (mfe4_atr >= 2.0)).astype(int)
bad    = ((npost <= 10) & (pnl4_atr <= 0.25)).astype(int)
alive4 = npost >= 4

# ─────────────────────────────────────────────────────────────────────────────
# 2. Load hC per-bar mapping
# ─────────────────────────────────────────────────────────────────────────────
print("Loading hC mapping ...")
hc_df = pd.read_parquet(OUT / "hc_perbar_mapping.parquet")
ts_to_year = dict(zip(ts, year))
hc_df["year"]  = hc_df.regime_start_ts.astype("int64").map(ts_to_year)
hc_df["k_idx"] = hc_df.bars_in_regime - 1    # bar index (== k column, but explicit)

# IS HardStall hC thresholds for HH/MH/LH classification
is_stall_hc = hc_df.loc[
    hc_df.state.isin(["HardStall", "SoftStall"]) & (hc_df.year < 2025), "hC"
].values
p33_hs = float(np.nanpercentile(is_stall_hc, 33))
p67_hs = float(np.nanpercentile(is_stall_hc, 67))
print(f"  IS stall hC thresholds: p33={p33_hs:.3f}  p67={p67_hs:.3f}")

def classify_state(state_s: pd.Series, hc_s: pd.Series) -> pd.Series:
    """Map state + hC into 5 pullback categories."""
    out = pd.Series("Other", index=state_s.index, dtype=object)
    out[state_s == "Healthy"]                                     = "Healthy"
    out[state_s == "DETER"]                                       = "DETER"
    stall = state_s.isin(["HardStall", "SoftStall"])
    out[stall & (hc_s >= p67_hs)]                                 = "HH-HardStall"
    out[stall & (hc_s >= p33_hs) & (hc_s < p67_hs)]              = "MH-HardStall"
    out[stall & (hc_s < p33_hs)]                                  = "LH-HardStall"
    return out

# ─────────────────────────────────────────────────────────────────────────────
# 3. Precompute first-HH-HardStall entry bars (for Section D)
# ─────────────────────────────────────────────────────────────────────────────
print("Building first-HH-HardStall lookup ...")
stall_rows = hc_df[hc_df.state.isin(["HardStall", "SoftStall"])].copy()
stall_rows["is_hh"]       = stall_rows.hC >= p67_hs
stall_rows["is_hh_slope"] = stall_rows.is_hh & (stall_rows.dhC.fillna(0) > 0)

ts_int = pd.Series(ts)   # df-aligned

def first_match_bar(flag_col: str) -> np.ndarray:
    """For each regime, first k_idx where flag_col is True. NaN if never."""
    grp = (stall_rows[stall_rows[flag_col]]
           .sort_values("k_idx")
           .groupby("regime_start_ts")["k_idx"]
           .first())
    return ts_int.map(grp).values.astype(float)   # NaN where not found

fhh_k  = first_match_bar("is_hh")        # first HH-HardStall bar index (may be NaN)
fhh_sl_k = first_match_bar("is_hh_slope")  # first HH-HardStall + slope>0

# ─────────────────────────────────────────────────────────────────────────────
# 4. Helpers
# ─────────────────────────────────────────────────────────────────────────────
def fmt_auc(a: float) -> str:
    return f"{a:.3f}" if np.isfinite(a) else "n/a"

def sim_pnl(entry_col_arr: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """Bar-mode PnL for a subset of regimes entering at given column indices."""
    sub_entry = O[idx, entry_col_arr[idx].astype(int)]
    sub_exit  = C[idx, np.minimum(npost[idx], 61)]
    return (sub_exit - sub_entry) * d[idx] * MULT - COMM

def split_oos(pnl_arr: np.ndarray, year_arr: np.ndarray) -> dict:
    """Return {y: (n, mean_ppt)} for each OOS year."""
    out = {}
    for y in OOS:
        m = year_arr == y
        out[y] = (m.sum(), float(pnl_arr[m].mean()) if m.sum() > 0 else np.nan)
    return out

def sim_row(label: str, pnl_arr: np.ndarray, year_arr: np.ndarray) -> str:
    spl = split_oos(pnl_arr, year_arr)
    n25, m25 = spl[2025]; n26, m26 = spl[2026]
    both_pos = (m25 > 0) and (m26 > 0)
    return (f"| {label} | {n25:,} | ${m25:+.0f} | {n26:,} | ${m26:+.0f} | "
            f"{'YES' if both_pos else 'no'} |")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Begin report
# ─────────────────────────────────────────────────────────────────────────────
R = [
    "# Trend Quality Emergence Curve", "",
    f"Capsule: {N:,} regimes (MAR-duration-skewed; fast-dying regimes under-represented).",
    f"IS HardStall hC thresholds: p33={p33_hs:.3f}, p67={p67_hs:.3f}",
    "",
    "**Bar-mode caveat**: all entry simulations use O[:,k] entry / hold-to-flip exit, 1 lot, "
    f"${COMM:.2f} commission. Expect ~$9-18/tr overstatement vs tick-mode. "
    "Use as opportunity landscape, not deployment-grade claim.",
    "",
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTION A: Predictive Quality at each age
# ─────────────────────────────────────────────────────────────────────────────
print("Section A: predictive quality ...")
R += [
    "## A. Predictive Quality (hC AUC and decile spread by regime age)", "",
    "hC from walk-forward KNN mapping (IS-only training, causally validated).",
    "AUC computed on OOS 2025+2026 regimes alive at that age.",
    "Top/bot decile = top/bottom 10% hC; rem-MFE = avg remaining MFE in ATR.",
    "",
    "| Age | n alive | % of pop | AUC hC→runner | AUC hC→bad | "
    "top-dec rem-MFE | bot-dec rem-MFE | spread |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
]

for k in AGES:
    alive = npost >= k
    pct   = 100.0 * alive.sum() / N

    hc_at_k = (hc_df[hc_df.bars_in_regime == k + 1]
               .drop_duplicates("regime_start_ts")
               .set_index("regime_start_ts")[["hC"]])

    # Build OOS subset
    oos_mask = alive & np.isin(year, OOS)
    sub = pd.DataFrame({
        "ts":      ts[oos_mask],
        "runner":  runner[oos_mask],
        "bad":     bad[oos_mask],
        "mfe_rem": mfe_remaining_after(k)[oos_mask],
    })
    sub["hC"] = sub.ts.map(hc_at_k.hC)
    valid = sub.hC.notna()
    sv = sub[valid]

    auc_r = roc_auc_score(sv.runner, sv.hC)   if sv.runner.sum() > 0 else np.nan
    auc_b = roc_auc_score(sv.bad,   -sv.hC)   if sv.bad.sum()    > 0 else np.nan

    q90 = sv.hC.quantile(0.9); q10 = sv.hC.quantile(0.1)
    top_rem = sv.loc[sv.hC >= q90, "mfe_rem"].mean()
    bot_rem = sv.loc[sv.hC <= q10, "mfe_rem"].mean()
    spread  = top_rem - bot_rem

    R.append(
        f"| Bar {k} | {alive.sum():,} | {pct:.0f}% | "
        f"{fmt_auc(auc_r)} | {fmt_auc(auc_b)} | "
        f"{top_rem:.2f} | {bot_rem:.2f} | {spread:.2f} |"
    )

R.append("")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION B: Opportunity Decay Curve
# ─────────────────────────────────────────────────────────────────────────────
print("Section B: opportunity decay ...")
R += [
    "## B. Opportunity Decay (bar-4 entry baseline; averaged over surviving population)", "",
    "mfe_consumed = max favourable excursion from bar-4 entry through bar k.",
    "mfe_remaining = max favourable excursion from bar k+1 to flip.",
    "mfe_total = max over all bars 4..flip per regime.",
    "% remaining = avg(remaining) / avg(total).",
    "",
    "| Age | n alive | mfe_total (ATR) | consumed (ATR) | remaining (ATR) | % remaining |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
]

for k in AGES:
    alive = npost >= k
    idx   = np.where(alive)[0]
    tot   = mfe_total[idx].mean()
    con   = mfe_consumed_at(k)[idx].mean()
    rem   = mfe_remaining_after(k)[idx].mean()
    pct   = 100.0 * rem / tot if tot > 0 else 0.0
    R.append(f"| Bar {k} | {alive.sum():,} | {tot:.2f} | {con:.2f} | {rem:.2f} | {pct:.0f}% |")

R.append("")

# Also: OOS-only opportunity decay (key for economic relevance)
R += [
    "### Opportunity decay — OOS only (2025+2026)", "",
    "| Age | n alive OOS | mfe_total | consumed | remaining | % remaining |",
    "| --- | ---: | ---: | ---: | ---: | ---: |",
]
for k in AGES:
    alive_oos = (npost >= k) & np.isin(year, OOS)
    idx = np.where(alive_oos)[0]
    if len(idx) == 0:
        continue
    tot = mfe_total[idx].mean()
    con = mfe_consumed_at(k)[idx].mean()
    rem = mfe_remaining_after(k)[idx].mean()
    pct = 100.0 * rem / tot if tot > 0 else 0.0
    R.append(f"| Bar {k} | {len(idx):,} | {tot:.2f} | {con:.2f} | {rem:.2f} | {pct:.0f}% |")

R.append("")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION C: Pullback State Analysis at key ages
# ─────────────────────────────────────────────────────────────────────────────
print("Section C: pullback state analysis ...")
R += [
    "## C. Pullback State Analysis (OOS 2025+2026)", "",
    "5 states: Healthy | HH-HardStall (stall bars with hC ≥ p67) | "
    "MH-HardStall (p33-p67) | LH-HardStall (<p33) | DETER.",
    "reignition = P(new MFE peak within 5 bars past this age).",
    "Entry sim (pnl†): causal — state observed at bar k close, enter bar k+1 open, 1 lot bar-mode.",
    "",
]

# Precompute peak-next-5 for reignition
peak_n5 = {}
for k in [4, 8, 12, 20]:
    wnd = (cols > k) & (cols <= k + 5)
    arr = np.where(wnd[None, :], fav_raw, np.nan)
    peak_n5[k] = np.nanmax(arr, axis=1)   # in points; NaN if no bars in window

for k in [4, 8, 12, 20]:
    R.append(f"### C.{[4,8,12,20].index(k)+1}  Bar {k} state snapshot")
    R.append("")

    alive_oos = (npost >= k) & np.isin(year, OOS)
    idx       = np.where(alive_oos)[0]

    # hC / state at this age
    hc_at_k = (hc_df[hc_df.bars_in_regime == k + 1]
               .drop_duplicates("regime_start_ts")
               .set_index("regime_start_ts")[["hC", "state"]])

    sub = pd.DataFrame({
        "ts":      ts[idx],
        "year":    year[idx],
        "runner":  runner[idx],
        "bad":     bad[idx],
        "npost":   npost[idx],
        "mfe_rem": mfe_remaining_after(k)[idx],
        "consumed": mfe_consumed_at(k)[idx],
    })
    sub = sub.merge(
        hc_at_k.reset_index().rename(columns={"regime_start_ts": "ts"}),
        on="ts", how="left"
    )
    sub["state_cat"] = classify_state(sub["state"], sub["hC"])

    # Entry PnL entering at bar k+1 open (CAUSAL: state known at bar k close)
    # Must survive to bar k+1.  Filter sub accordingly.
    can_enter_k1 = npost[idx] >= k + 1
    sub["can_enter"] = can_enter_k1
    entry_k  = np.where(can_enter_k1, O[idx, np.minimum(k + 1, NCOL - 1)], np.nan)
    exit_k   = C[idx, np.minimum(npost[idx], 61)]
    sub["pnl_k"] = (exit_k - entry_k) * d[idx] * MULT - COMM
    sub.loc[~sub.can_enter, "pnl_k"] = np.nan

    # Reignition
    con_pts    = sub.consumed.values * atr[idx]          # consumed back to points
    peak_arr   = peak_n5[k][idx]
    sub["reignition"] = (peak_arr > con_pts) & np.isfinite(peak_arr)

    # Flip probability
    remaining_bars = sub.npost.values - k
    sub["flip_le3"] = remaining_bars <= 3
    sub["flip_le5"] = remaining_bars <= 5

    R.append("| State | n | bad% | runner% | rem-MFE (ATR) | pnl $/tr† | "
             "P(flip≤3) | P(flip≤5) | P(reignite) |")
    R.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")

    for st in STATE_ORDER:
        sg = sub[sub.state_cat == st]
        if len(sg) < 5:
            continue
        sg_e = sg[sg.can_enter]   # subset that can enter (npost >= k+1)
        pnl_str = f"${sg_e.pnl_k.mean():+.0f}" if len(sg_e) > 0 else "—"
        R.append(
            f"| {st} | {len(sg):,} | "
            f"{sg.bad.mean()*100:.0f}% | {sg.runner.mean()*100:.0f}% | "
            f"{sg.mfe_rem.mean():.2f} | {pnl_str} | "
            f"{sg.flip_le3.mean()*100:.0f}% | {sg.flip_le5.mean()*100:.0f}% | "
            f"{sg.reignition.mean()*100:.0f}% |"
        )

    sub_e = sub[sub.can_enter]
    R.append(
        f"| **ALL** | {len(sub):,} | "
        f"{sub.bad.mean()*100:.0f}% | {sub.runner.mean()*100:.0f}% | "
        f"{sub.mfe_rem.mean():.2f} | ${sub_e.pnl_k.mean():+.0f} | "
        f"{sub.flip_le3.mean()*100:.0f}% | {sub.flip_le5.mean()*100:.0f}% | "
        f"{sub.reignition.mean()*100:.0f}% |"
    )
    R.append("†pnl = causal: enter bar k+1 open (state observed at bar k close), "
             "exit hold-to-flip. Bar-mode 1-lot.")
    R.append("")

    # Year breakdown for ALL
    for y in OOS:
        sg = sub[sub.year == y]
        R.append(f"  *{y}: n={len(sg):,}  $/tr=${sg.pnl_k.mean():+.0f}  "
                 f"runner={sg.runner.mean()*100:.0f}%  bad={sg.bad.mean()*100:.0f}%*")
    R.append("")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION D: Entry Simulation
# ─────────────────────────────────────────────────────────────────────────────
print("Section D: entry simulation ...")
R += [
    "## D. Entry Simulation (bar-mode, 1 lot, OOS 2025/2026 separate)", "",
    "Age entries: enter at O[:,k] (bar k open). No state conditioning.",
    "State entries: enter at O[:,k_state+1] (bar after state observed).",
    "Survivorship: each row's population is conditioned on regime surviving to entry bar.",
    "",
    "| Entry | 2025 n | 2025 $/tr | 2026 n | 2026 $/tr | both>0? |",
    "| --- | ---: | ---: | ---: | ---: | :---: |",
]

# Bar-4 baseline (bar-mode)
alive = npost >= 4
idx   = np.where(alive)[0]
pnl   = pnl4[idx]
R.append(sim_row("bar-4 baseline (bar-mode)", pnl, year[idx]))

# NT fills baseline (per-contract, for reference)
try:
    bt25 = pd.read_parquet(OUT / "baseline_2025" / "trades.parquet")
    bt26 = pd.read_parquet(OUT / "baseline_2026" / "trades.parquet")
    n25 = len(bt25); m25 = bt25.net_pnl.sum() / bt25.entry_contracts.sum()
    n26 = len(bt26); m26 = bt26.net_pnl.sum() / bt26.entry_contracts.sum()
    R.append(f"| bar-4 NT fills (per contract) | {n25:,} | ${m25:+.1f} | "
             f"{n26:,} | ${m26:+.1f} | {'YES' if m25>0 and m26>0 else 'no'} |")
except Exception:
    pass

# Age entries: bars 6, 8, 10, 12, 15, 20
for k in [6, 8, 10, 12, 15, 20]:
    alive = npost >= k
    idx   = np.where(alive)[0]
    entry = O[idx, k]
    exit_ = C[idx, np.minimum(npost[idx], 61)]
    pnl   = (exit_ - entry) * d[idx] * MULT - COMM
    R.append(sim_row(f"bar-{k} age entry", pnl, year[idx]))

R.append("| | | | | | |")

# First HH-HardStall entry
has_fhh  = np.isfinite(fhh_k)
fhh_k_i  = np.where(has_fhh, fhh_k, 0).astype(int)
can_enter = has_fhh & (fhh_k_i + 1 < NCOL) & (npost >= fhh_k_i + 1)
idx       = np.where(can_enter)[0]
entry_col = fhh_k_i[idx] + 1               # enter bar after HH-HardStall observed
entry     = O[idx, entry_col]
exit_     = C[idx, np.minimum(npost[idx], 61)]
pnl       = (exit_ - entry) * d[idx] * MULT - COMM
R.append(sim_row("first HH-HardStall (enter next bar)", pnl, year[idx]))

# Average entry bar for first-HH-HardStall
if len(idx) > 0:
    avg_entry_bar = fhh_k_i[idx].mean()
    R.append(f"  *(avg first-HH-HS bar: {avg_entry_bar:.1f}; "
             f"{100*len(idx)/N:.0f}% of regimes have a HH-HardStall before bar 29)*")

# First HH-HardStall + improving slope (dhC>0)
has_sl   = np.isfinite(fhh_sl_k)
sl_k_i   = np.where(has_sl, fhh_sl_k, 0).astype(int)
can_sl   = has_sl & (sl_k_i + 1 < NCOL) & (npost >= sl_k_i + 1)
idx      = np.where(can_sl)[0]
entry_col = sl_k_i[idx] + 1
entry     = O[idx, entry_col]
exit_     = C[idx, np.minimum(npost[idx], 61)]
pnl       = (exit_ - entry) * d[idx] * MULT - COMM
R.append(sim_row("first HH-HardStall + slope>0", pnl, year[idx]))

R.append("")

# Survivor-conditioned state entry sims (enter only when in a given state at bar 8)
R += [
    "### State-conditioned entry at bar 8 (enter bar 8 open when in state at bar 7 close)", "",
    "| State at bar 7 | n OOS | 2025 $/tr | 2026 $/tr | both>0? |",
    "| --- | ---: | ---: | ---: | :---: |",
]
hc_at_7 = (hc_df[hc_df.bars_in_regime == 8]
           .drop_duplicates("regime_start_ts")
           .set_index("regime_start_ts")[["hC", "state"]])

alive8_oos = (npost >= 8) & np.isin(year, OOS)
idx8       = np.where(alive8_oos)[0]

sub8 = pd.DataFrame({"ts": ts[idx8], "year": year[idx8]})
sub8 = sub8.merge(hc_at_7.reset_index().rename(columns={"regime_start_ts": "ts"}),
                  on="ts", how="left")
sub8["state_cat"] = classify_state(sub8["state"].fillna(""), sub8["hC"].fillna(0.0))

entry8 = O[idx8, 8]
exit8  = C[idx8, np.minimum(npost[idx8], 61)]
pnl8   = (exit8 - entry8) * d[idx8] * MULT - COMM
sub8["pnl"] = pnl8

for st in STATE_ORDER:
    sg = sub8[sub8.state_cat == st]
    if len(sg) < 10:
        continue
    m25 = sg.loc[sg.year==2025, "pnl"].mean() if (sg.year==2025).sum() > 0 else np.nan
    m26 = sg.loc[sg.year==2026, "pnl"].mean() if (sg.year==2026).sum() > 0 else np.nan
    n_oos = len(sg)
    both  = m25 > 0 and m26 > 0
    R.append(f"| {st} | {n_oos:,} | ${m25:+.0f} | ${m26:+.0f} | {'YES' if both else 'no'} |")

R.append(f"| ALL | {len(sub8):,} | ${sub8.loc[sub8.year==2025,'pnl'].mean():+.0f} | "
         f"${sub8.loc[sub8.year==2026,'pnl'].mean():+.0f} | no |")
R.append("")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION E: 5-Point Data-Driven Conclusion
# ─────────────────────────────────────────────────────────────────────────────
print("Section E: conclusion ...")

oos_mask_b4 = (npost >= 4) & np.isin(year, OOS)
oos_mfe_total = mfe_total[oos_mask_b4].mean()
oos_mfe_b8    = mfe_remaining_after(8)[ (npost >= 8)  & np.isin(year, OOS)].mean()
oos_mfe_b12   = mfe_remaining_after(12)[(npost >= 12) & np.isin(year, OOS)].mean()
oos_mfe_b20   = mfe_remaining_after(20)[(npost >= 20) & np.isin(year, OOS)].mean()

pct_alive_b8  = 100.0 * ((npost >= 8)  & np.isin(year, OOS)).sum() / oos_mask_b4.sum()
pct_alive_b12 = 100.0 * ((npost >= 12) & np.isin(year, OOS)).sum() / oos_mask_b4.sum()
pct_alive_b20 = 100.0 * ((npost >= 20) & np.isin(year, OOS)).sum() / oos_mask_b4.sum()

# Section D sim results (from the output)
# bar-8 age entry: 2025=$-1, 2026=$-25  → both negative
# first HH-HardStall: 2025=$-2, 2026=$-26  → both negative
# state-conditioned bar-8 Healthy: 2025=$-4, 2026=$-23 → both negative
# state-conditioned bar-8 HH-HardStall: 2025=$-2, 2026=$-24 → both negative
# bar-20 age entry (best): 2025=$+2, 2026=$-28 → 2026 fails

# Conclusion: composition separates dramatically but expectancy does not follow.

R += [
    "## E. 5-Point Conclusion", "",
    f"Full-pop avg total MFE (bar-4 entry, OOS): **{oos_mfe_total:.2f} ATR**  "
    f"| NT per-contract baseline: 2025 $-9/tr, 2026 $-32/tr",
    "",
    "### 1. Earliest age where trend quality is statistically observable",
    "",
    "**Bar 6** — AUC jumps from 0.638 (bar 4) to 0.704 at bar 6 for runner prediction. "
    "By bar 8 runner AUC = 0.715, bad AUC = 0.731. "
    "Top-vs-bottom decile MFE spread reaches 3.1 ATR at bar 8 (vs 2.2 at bar 4). "
    "State-level composition at bar 8 is dramatic: "
    "Healthy/HH-HardStall = 71-72% runner, 5-7% bad; "
    "LH-HardStall/DETER = 21-40% runner, 28-29% bad. "
    "**Statistical separability: bar 6. Practically strong: bar 8.**",
    "",
    "### 2. Earliest age where trend quality is economically useful",
    "",
    "**Never, based on this data.** "
    "Every unconditional age entry (bars 6/8/10/12/15/20) is negative in 2026 (−$14 to −$30/tr). "
    "Every state-conditioned bar-8 entry is negative in 2026 (−$14 to −$36/tr). "
    "First HH-HardStall entry: 2025 −$2, 2026 −$26. "
    "Even at bar 20 (87% runner rate, 0% bad): 2025 +$2, 2026 −$28. "
    "**Composition is informative. Expectancy is not.**",
    "",
    "### 3. Remaining opportunity at the statistically observable age (bar 8)",
    "",
    f"At bar 8 (OOS): avg remaining MFE = **{oos_mfe_b8:.2f} ATR** "
    f"({100*oos_mfe_b8/oos_mfe_total:.0f}% of total MFE). "
    f"Surviving population = **{pct_alive_b8:.0f}%** of bar-4-alive regimes — "
    f"positively selected (longer/stronger regimes). "
    f"At bar 12: {oos_mfe_b12:.2f} ATR ({100*oos_mfe_b12/oos_mfe_total:.0f}%) — "
    f"{pct_alive_b12:.0f}% alive. "
    f"At bar 20: {oos_mfe_b20:.2f} ATR ({100*oos_mfe_b20/oos_mfe_total:.0f}%) — "
    f"{pct_alive_b20:.0f}% alive. "
    "Opportunity does NOT decay — it appears to grow because survivorship selects "
    "stronger regimes. But the remaining-MFE is the MAX excursion, "
    "not the expected hold-to-flip PnL. "
    "The actual expectancy (hold-to-flip from entry) stays flat near −$25 regardless of entry age.",
    "",
    "### 4. Whether a pullback-entry framework is more viable than regime-birth entry",
    "",
    "**No — the composition gain is real; the expectancy gain is not.** "
    "At bar 8, HH-HardStall state has: bad=7%, runner=72%, rem-MFE=4.19 ATR. "
    "vs the bar-4 full population: bad=45%, runner=36%, rem-MFE=2.20 ATR. "
    "Dramatic composition improvement. "
    "But the causal bar-8 entry (state seen at bar 7, enter bar 8 open) for "
    "HH-HardStall regimes: 2025 −$2/tr, 2026 −$24/tr — "
    "essentially identical to unconditional bar-8 entry (−$1/−$25). "
    "The state separation exists in future-outcome space, not in the tradeable next-bar direction. "
    "**Pullback framework: composition artifact confirmed, same conclusion as "
    "[[regime_health_decay_no_leadtime_1m]].**",
    "",
    "### 5. Whether the trend-quality thesis is monetizable after costs",
    "",
    "**NO. Trend quality is measurable but not monetizable with OHLCV inputs.** "
    "Summary: "
    "(a) hC separates regimes well (AUC 0.71-0.73) — real signal. "
    "(b) High-quality regimes genuinely have more remaining MFE and higher runner rates. "
    "(c) But entering any of them at any age from 4 to 20 yields the same "
    "approximate expectancy: roughly −$1 to −$30/tr depending on year, "
    "regardless of state, timing, or composition filter. "
    "The pattern is identical to the earlier finding that "
    "pullback severity predicts recovery odds but is monetarily inert — "
    "price has already incorporated the quality signal into the current close. "
    "**The opportunity MFE is real; capturing it requires a non-OHLCV trigger "
    "(order flow, book, footprint) to identify the favorable resolution direction within "
    "the already-established trend.** "
    "Without that, trend quality is a descriptive feature, not a tradeable edge.",
    "",
    "---",
    "",
    "**OVERALL VERDICT: Trend-quality thesis CLOSED for OHLCV-only inputs.** "
    "This study represents the final angle of the regime-flip signal class: "
    "regime birth (V_A), bar-3 prediction (Model B / BadShort KNN), "
    "per-bar health monitoring (hC KNN), pullback states (HH-HardStall), "
    "and now delayed entry at each regime age. All angles confirm the same ceiling. "
    "Next viable direction: order-flow / book data on this same regime population.",
]

(OUT / "trend_quality_emergence.md").write_text("\n".join(R), encoding="utf-8")
print("Wrote trend_quality_emergence.md")


if __name__ == "__main__":
    pass
