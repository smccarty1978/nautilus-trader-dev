# Look-Ahead & Timestamp Audit

**Date:** 2026-06-16
**Scope:**
- `studies/regime_dna_knn/bar4_knn_money_gate.py` (primary)
- `studies/regime_dna_knn/bar4_knn_path_atlas.py` (build_states, FEATS, CLASSES)
- `studies/regime_dna_knn/progressive_separability.py` (build / matrix construction)
- `studies/regime_dna_knn/early_health_filter.py` (capsule loader, compute_labels_features)

**Auditor:** lookahead-auditor v1

---

## Summary

- Critical: 0
- Warning: 2
- Note: 3

---

## Critical findings

None.

---

## Warnings

### [W1] `bar4_knn_path_atlas.py:54-62` — `cls` label anchored to bar-4 OPEN, not bar-5 OPEN (entry mismatch)

**Description.**
`build_states` computes `entry = O[:, 4]` (post-flip bar 4's OPEN) and then
`favE = H[:, 4:] - entry` / `advE = entry - L[:, 4:]` to get `mfe_e` / `mae_e`.
The `cls` label (Runner / Failure / Continuation / Chop) is therefore defined
relative to a bar-4-open entry price.

The money gate enters at bar-5 OPEN (`ENTRY_COL = 5`, `O[gi, 5]`). These are
different prices. Bar 4's intrabar H/L (which the bar-4-open entry captures) is
already closed and known at signal time — it cannot be traded at bar-5 open.

**Concrete impact.**
A trade whose price jumped favorably WITHIN bar 4 (after its open but before close)
will have a higher `mfe_e` relative to bar-4-open than relative to bar-5-open. Such
trades may be classified as Runner when, from bar-5-open entry, they would be Chop
or Continuation. As a result:

1. The IS reference set's `cls` distribution may be systematically optimistic about
   Runner rates relative to the actual bar-5-open trades being evaluated.
2. The `pRun` scores derived from IS-neighbor `cls` labels may be slightly inflated.
3. The `isRun` / `isFail` evaluation columns, which use the same `cls`, will also be
   anchored to bar-4 open — so the "Run%" column in the output tables reflects a
   different trade than what is actually being executed and priced.

**Why this is a Warning, not Critical.**
The PnL itself (`pnl = (flip_c - di*EXIT - fill) * di * MULT - COMM`) is computed
using bar-5-open entry and the true terminal flip close. It is correct and unbiased
regardless of how `cls` is defined. The money test stands. The issue only affects
(a) the signal's calibration quality — `pRun` is trained against a slightly wrong
label — and (b) the descriptive Run%/Fail% columns used to characterize cohorts.
If the study's conclusion is driven by the PnL result (net/tr, PF, year split),
those numbers are clean. If a positive result is being framed as "the KNN identified
true Runners and those Runners make money," that framing is weakened because `cls`
and PnL are measured from different entry points.

**Recommended fix (do not apply):** In `build_states`, redefine `entry = O[:, 5]`
(bar-5 open) for all label-construction purposes. `mfe_e`, `mae_e`, and `flip_bars`
should be computed from `H[:, 5:]` / `L[:, 5:]` / `n - 5` so that `cls` corresponds
to the trade that is actually being placed. `hk`, `lk` used for features in the
`for k in BARS` loop (starting at k=4) would remain as-is (they start at bar 4).

---

### [W2] `bar4_knn_money_gate.py:71` — `ni = np.minimum(n[gi], 61)` truncates forward MFE/MAE for long-running trades

**Description.**
`ni = np.minimum(n[gi], 61)` caps the forward MFE/MAE scan at bar 61 for the
descriptive `fav`/`adv` columns. The matrix `H`/`L` is 62 columns wide (cols 0–61),
so any post-flip bars beyond col 61 are silently absent. For a trade with 80
post-flip bars, `fav` / `adv` only reflect bars 5–61.

**Concrete impact.**
This does NOT affect PnL — `flip_c` reads from the raw uncapped `df.post_c` list
(`df.post_c.apply(lambda x: float(x[-1]))`), which is correct. It only affects the
descriptive `avgMFE` / `avgMAE` columns in the output table. For very long trades
(n_post > 61), reported `avgMFE` will be understated relative to the true eventual
MFE. This matters if the study uses `avgMFE`/`avgMAE` ratios to characterize cohort
quality; those ratios will look better (lower MAE, lower MFE) than reality for the
long-tail trades.

The same truncation applies to `cls` in `build_states` (line 56: `H[:, 4:]` on the
capped matrix), so Runners whose most favorable bars occur after bar 61 may be
misclassified. This compounds Warning W1.

**Recommended fix (do not apply):** For descriptive MFE/MAE only: scan the raw
`post_h` / `post_l` lists directly (as the capsule loader stores them uncapped) from
`ENTRY_COL` onward, rather than relying on the capped matrix. The matrix cap of 62
bars was designed for the progressive-separability study's feature windows; the
money-gate's forward scan should not be constrained by it.

---

## Notes

### [N1] `bar4_knn_path_atlas.py:33,116` — four FEATS are structural constants at k=4

At `k = DECISION_BAR = 4` the following features in `FEATS` are degenerate:

- `bar_idx` = `k - 4` = 0 always.
- `progress_count`: at k=4, `hk = H[i, 4:5]` is one element; `newext` is always
  `[True]` by initialization; `prog = 1` always.
- `consec_noncont`: `stall` loop finds `newext[0] = True` immediately; `stall = 0`
  always.
- `vol_exp`: `vmean = nanmean(V[i, 4:5])` = `V[i, 4]`; `vexp = V[i,4] / V[i,4]`
  = 1.0 always (when non-zero).

These four features contribute zero variance to the 12-dimensional feature space at
k=4. Because KNN uses Euclidean distance over all 12 dimensions after
standardization, and `sd[sd == 0] = 1` (line 57) prevents divide-by-zero, the
zero-variance columns simply drop out of the distance metric. No bias is introduced.

However, 4 of 12 features being constants means the effective dimensionality at k=4
is 8, and the standardization step's `sd[sd==0]=1` guard is the only thing keeping
this from being a bug. This is a fragile assumption — if a future data cut has all
trades at k=4 with zero variance in a non-constant feature (e.g., a flat-market
period), that feature would also silently collapse to a constant and be excluded.

**Recommended fix (do not apply):** Drop `bar_idx`, `progress_count`,
`consec_noncont`, and `vol_exp` from `FEATS` when `k = DECISION_BAR = 4`, or define
a `FEATS_BAR4` subset that excludes them. This makes the effective feature set
explicit rather than relying on the zero-variance guard.

---

### [N2] `bar4_knn_money_gate.py:91-92` — cohort thresholds are OOS-relative; study acknowledges but no IS-derived fallback reported

`qR90`, `qR80`, `qF50`, `qF30`, `qF20` are computed as quantiles of `pRun` /
`pFail` over the full OOS population (2025+2026 combined). These percentile cuts are
then applied to the same OOS population to define cohorts, and those cohorts are
evaluated on the same OOS pnl.

This is not look-ahead in the traditional sense (the thresholds use predicted
probabilities, not true outcomes or pnl), and the script's header correctly
describes this limitation and names the both-year split as the robustness gate.

However, the thresholds will shift if the OOS pRun/pFail distribution shifts between
2025 and 2026. A cohort defined by "top 10% of pRun across 2025+2026" is not
identical to what a 2025-only deployment would have selected. For the per-year split
columns (`n25`, `n26`) to be meaningful as independent validation, the threshold
should ideally be derived from IS data or from 2025-only and applied to 2026.

**Recommended fix (do not apply):** Add a secondary output that recomputes thresholds
from the IS pRun/pFail distribution (available as `isk["pRun"]` / `isk["pFail"]` if
stored back, or via a second KNN pass). Report cohort results using IS-anchored
thresholds. This would be the deployment-valid framing.

---

### [N3] `bar4_knn_money_gate.py:74` — `flip_c` reads the last element of raw post_c, which is the opposite-regime flip bar close

`flip_c = df.post_c.apply(lambda x: float(x[-1])).values[gi]`

`post_c` is built in `CapsuleReplay.on_bucket_closed` (early_health_filter.py:100):
each post-flip bar is appended to `c["post"]`, including the bar that triggers the
opposite flip. The last element is therefore the close of the terminal opposite-flip
bar. This is the correct hold-to-flip exit price and is NOT look-ahead.

The EXIT slip is then applied adversely: `flip_c - di * EXIT` for long (sells at
flip_c minus 1 tick), `flip_c - (-1)*EXIT` = `flip_c + EXIT` for short (buys back
1 tick above flip close). Both are adverse. Confirmed correct.

One stylistic concern: if `post_c` is an empty list (n_post = 0), `x[-1]` would
raise IndexError. The `has5` gate (line 69: `n[gi] > 4`) ensures n_post >= 5 before
this code runs, so the list always has at least 5 elements. This is safe, but the
dependency is non-local (the guard is 5 lines above and the risk is not documented).
A defensive `assert len(x) > 0` or a check on `n_post` at the flip_c assignment
would make this explicit.

---

## Clean checks

- **A (NautilusTrader timestamps):** Not applicable to this offline study (no NT
  strategy, no BacktestEngine). The upstream catalog uses `NQ_v0_2020_2026` (v.0
  continuous) and 1s bars via `ts_init` ordering, consistent with the project catalog
  rules.

- **B1 (no center=True rolling):** No rolling computations present.

- **B2 (features at bar i use only data through bar i):** Confirmed. At k=4,
  `hk = H[i, 4:5]`, `lk = L[i, 4:5]`, `pnl_now = C[i, 4]`. No column >= 5 is read
  for any feature.

- **B4 (no .shift(-N) in feature path):** Confirmed. No negative-lag shift anywhere
  in the feature path.

- **B5 (no bfill):** Confirmed. No bfill present. NaN fill uses
  `sd[sd == 0] = 1` (scalar guard, not value fill) and the standardized inputs
  include `np.float32` NaN passthrough — benign in this context.

- **B7 (normalization uses IS-only statistics):** Confirmed. `mu = Xis.mean(0)`,
  `sd = Xis.std(0)` are computed on IS rows only (line 57) and applied to both IS
  fit and OOS query.

- **C1 (labels use future windows by design):** Confirmed. `cls` is a forward label
  using the full post-bar-4 path. It is attached to the IS reference only and is
  used via KNN lookup — never as an input feature. `isRun` / `isFail` in OOS rows
  are also forward labels used only for evaluation, not for cohort selection.

- **C3 (temporal train/test split):** Confirmed. IS = year < 2025, OOS = year >= 2025.
  No random split. No shuffle.

- **D (train/serve skew):** Not applicable. This is a pure offline study. No live
  strategy is defined.

- **KNN IS contamination:** Confirmed clean. `nn.fit((Xis - mu) / sd)` uses IS rows
  only. `nbcls = isk.cls.values[idx]` indexes back into IS. OOS true labels are
  never in the KNN reference set.

- **Cohort selection uses predicted probabilities only:** Confirmed. Lines 90–92
  compute quantiles on `ook.pRun` and `ook.pFail` (KNN predictions). The `isRun` /
  `isFail` columns (true labels) and `pnl` are assigned after (lines 86–87) and are
  only used for evaluation inside `stats()`. The `winners` filter (line 134) uses
  `st['n25']`, `st['n26']`, `st['pf']` — pnl-derived quantities — but that is
  evaluation, not cohort selection.

- **Entry causality (bar 5 after bar-4 signal):** Confirmed. `ENTRY_COL = 5`,
  `entry = O[gi, 5]`. The `has5` gate ensures bar 5 exists. No column < 5 is used
  in any feature at k=4.

- **Entry slip direction:** Confirmed adverse. `fill = entry + di * ENTRY` adds slip
  in the direction of the trade (long pays more, short receives less).

- **Exit slip direction:** Confirmed adverse. `flip_c - di * EXIT` subtracts slip
  in trade direction before the directional multiply. Long exits below flip close,
  short exits above flip close.

- **Commission:** Confirmed applied. `- COMM` ($5 RT) on every trade.

- **maxDD time ordering:** Confirmed. `ook.sort_values("rid")` (line 88) sorts by
  `regime_id`, which is constructed as `year * 100_000 + sequential_ridx` in the
  capsule builder, producing chronological order within a year. Cross-year order is
  correct because the year component dominates. `maxdd()` then applies
  `np.cumsum` on the time-ordered pnl vector.

---

*Audit complete. Findings reflect read-only static analysis. Dynamic bugs (e.g.,
runtime NaN propagation, OOS data availability) are out of scope.*
