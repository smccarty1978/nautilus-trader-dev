# Look-Ahead, Timestamp & Completion Audit — fable5_established_regime_weakness_fade

**Date:** 2026-07-13
**Scope:** `SPEC.md`, `common.py`, `build_stage1.py`, `analyze_stage1.py`, `evaluate_stage1.py`,
`run_stage2_ohlc.py`, `analyze_stage2.py`, `stage2_frozen_policy.json`, all `results/*`,
all `audit/*`, both `_snapshots/*` folders. This is a **post-execution completion audit**
(the full Stage-1 + Stage-2 pipeline has already run for 2021-2025 and 2026).
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 1 (process/documentation, not a numerical defect)
- Warning: 4
- Note: 3

The underlying C1 direction-source defect described in the prior `audit/completion_audit.md`
(FAIL) **is fixed in the artifacts currently in `results/`**, and the fix is independently
verified two ways below (not merely re-asserted). However, the repository's own audit trail
has not been closed out to reflect this, and two disclosure/hygiene gaps remain material
enough to flag before anyone treats this study as "done."

---

## CRITICAL

### [Process] `audit/completion_audit.md` still reads FAIL / 1 CRITICAL / "do not report the study complete" — no superseding PASS completion audit exists on disk

**Artifact:** `audit/completion_audit.md` (unchanged since it was written, timestamp 2026-07-13 13:45:44)

The prior completion audit found that `run_stage2_ohlc.py` inherited the exact stale
`flip_context_atlas` F1 direction fallback that Stage 1 had already proven unusable
(36.73% of 2025 candidates, 34.66% of 2025 trades wrong-signed) and explicitly instructed:
*"Do not report the study complete and do not use the current final decision... request a
new completion audit."* That document is still the only completion audit in `audit/` and
it still says FAIL. Per CLAUDE.md's mandatory audit-gate workflow ("Repeat 3-5 until zero
CRITICAL... Only then report back"), a study should never be represented as finished while
its own completion audit artifact reads FAIL, regardless of whether the underlying code was
subsequently fixed.

**Verification performed for this audit (see Warning/Note items below for detail):** the C1
defect described in that document **has** been fixed in the code and re-executed — confirmed
independently two ways (Section 4 below): (a) `run_stage2_ohlc.py`'s own fail-fast parity
assert against `causal_scores.parquet` direction (0 mismatches, both years), and (b) a fresh
cross-check performed for this audit joining `results/stage2_trades_2025.parquet` against
`results/stage1_regime_metrics.parquet` on `regime_start_ns` — an independent second
computation of regime direction from a completely separate code path (Stage 1's
`build_stage1.py`, not Stage 2's `run_stage2_ohlc.py`) — **0/2,103 mismatches**. This is
strong evidence the fix is real, not merely asserted.

This finding is filed as CRITICAL because of the *process* gap (a stale FAIL artifact sitting
next to a final report and a decision that the study should not, per its own prior audit, be
using), not because the current numbers are wrong. This document is intended to serve as the
superseding completion audit; it should not be the only place this is recorded — recommend
either updating `completion_audit.md`'s status line or adding an explicit "SUPERSEDED, see
completion_lookahead_audit.md" note to it (read-only recommendation; not applied by this
auditor).

---

## WARNINGS

### [W1] `_snapshots/stage2_broken_direction_20260713_1335/` is mislabeled for its 2025 contents — it is byte-identical to the *current, fixed* 2025 output, not the broken run

**Artifacts compared (read-only, hash/`DataFrame.equals` verified):**

- `results/stage2_trades_2025.parquet` (2,103 rows) **==** (byte-identical, `.equals()` True)
  `_snapshots/stage2_broken_direction_20260713_1335/stage2_trades_2025.parquet` (2,103 rows).
  Same for `stage2_reconciliation_2025.json` (identical JSON, same `policy_sha256`).
- The **actual** pre-fix, broken-direction 2025 Stage-2 run is preserved elsewhere, under a
  folder name that does not indicate it holds broken Stage-2 data:
  `_snapshots/results_20260713_1340/stage2_trades_2025.parquet` — **2,403 rows**, with
  `prevailing_direction` split 2,037 long / 366 short (vs. the fixed run's 2,089 long / 34
  short at the candidate level, 2,080 short-entry / 23 long-entry trades). This 2,403/2,103
  trade-count delta (≈14%) and the direction re-labeling of ~350+ trades is the real
  before/after evidence of the C1 fix, and it matches `completion_audit.md`'s cited numbers
  (2,505 candidates / 2,403 trades / 920 mismatched candidates / 833 mismatched trades)
  almost exactly.
- `_snapshots/stage2_broken_direction_20260713_1335/stage2_trades_2026.parquet` differs from
  `results/stage2_trades_2026.parquet` in **only** two floating-point columns
  (`running_mfe_atr`, `retained_mfe_ratio`, differences at the 3rd decimal), with
  `entry_direction`, `prevailing_direction`, all fill prices, exit reasons and PnL fields
  100% identical. This is consistent with `completion_audit.md`'s own finding that "For
  2026, Stage-2 candidate direction matches the causal-score direction on all 885
  candidates" even under the broken code — 2026's atlas `direction` column is populated
  directly (0% NaN per the Pass-2 pre-execution audit's provenance table), so the C1 bug
  never actually altered 2026 economics, broken or fixed.

**Why this matters:** the user-facing task (and a reasonable future auditor) would compare
`results/` against `_snapshots/stage2_broken_direction_20260713_1335/` expecting to see the
magnitude of the fix. For 2025 that comparison silently shows **zero difference** and would
falsely suggest either "no bug existed" or "the fix did nothing" — the true before/after
pair for 2025 is `_snapshots/results_20260713_1340/` vs. `results/`, a folder whose name
gives no indication it contains the broken Stage-2 artifact. The `stage2_broken_direction_*`
folder appears to have been reused as a general dumping ground across multiple points in time
(files inside it carry write timestamps from 13:35:55 through 13:47:25 — spanning both
before and after the loader fix at 13:40:17), rather than representing one atomic snapshot.

**Recommendation (do not apply):** rename/reorganize snapshots so each folder is an atomic,
correctly-labeled point-in-time capture (e.g. `_snapshots/stage2_2025_broken_2403trades/`),
or at minimum add a README inside each snapshot folder recording what code version/run
produced its contents and when.

### [W2] Direction asymmetry (2,080 short vs. 23 long entries in 2025; 846 vs. 30 in 2026) is real and correctly signed, but is **not** explained by the established-regime filter population — it is inherited almost entirely from the frozen W4 model's direction-asymmetric score distribution, and this attribution is undisclosed in `final_report.md`

Per the audit brief's request, I checked whether the extreme direction skew reflects a
genuine population property (bullish established regimes vastly outnumbering bearish ones)
or a residual sign defect.

- **Raw 2025 regime population is balanced:** `results/stage1_regime_metrics.parquet`,
  `period=="validation"`: 13,583 short-direction vs. 13,582 long-direction regimes (~50/50).
- **Regimes passing `peak_mfe_atr>=1.0 & duration_s>=120`** (a loose proxy for the Stage-2
  filter's age/MFE legs): 8,181 short vs. 8,106 long — still ~50/50.
- **Regimes additionally passing `retained_flip>=0.5 & new_progress_windows>=2`** (closest
  full-filter proxy available in Stage-1's hindsight columns): 1,317 short vs. 1,787 long —
  57.6%/42.4%. A real skew, but nowhere near the ~98%/2% seen in Stage-2 candidates/trades.
- **Stage-2 candidates** (`results/stage2_candidates_2025.parquet`, the "established filter
  true AND W4 crossed" population): 2,089 long-prevailing vs. 34 short-prevailing —
  98.4%/1.6%. The asymmetry jumps sharply at exactly the point the W4 trigger is applied,
  not at the point the established-regime filter alone is applied.
- **Root cause located:** `studies/fable5_pre_flip_d10_reversal_entry/_work/causal_scores.parquet`
  (the frozen, reused W4 score stream), 2025 rows grouped by `direction`: mean `w4_score` for
  `direction=+1` (long/bullish prevailing) is **0.366** (median 0.335); for `direction=-1`
  (short/bearish prevailing) is **0.190** (median 0.120). Against the frozen absolute
  threshold `0.618328`, checkpoints inside long-prevailing regimes cross far more often
  purely because the reused model's score distribution sits systematically higher for that
  direction — this is a property of the **frozen, out-of-scope W4 model** (built and frozen
  in a different, already-completed study), not a bug introduced by this study's own code.

**Why this is a Warning, not clean:** `results/final_report.md` reports the 2,080/23 (and
846/30) split with no explanation, and shows the tiny long-side buckets with eye-catching
metrics (2025 long: 23 trades, PF 2.16, +$185.73/tr net; 2026 long: 30 trades, PF 0.49,
-$141.75/tr net — a sign flip on a 23-30 trade sample). Absent the attribution above, a
reader could mistake this for either (a) a residual direction bug, or (b) a genuine
directional edge on the long side, when it is neither — it is a single-digit-to-double-digit
sample size driven by how rarely the frozen W4 model's score distribution allows a
short-prevailing-regime candidate to qualify at all. Both `2025_direction`/`2026_direction`
rows in the results table should carry a footnote to this effect, and the long-side PF/net
figures should not be used to support any directional claim given n=23 and n=30.

**Recommended fix (do not apply):** add one sentence to `final_report.md`'s Results section
attributing the direction split to the frozen W4 model's score-distribution asymmetry
(cite the 0.366 vs. 0.190 mean-score gap), and mark the long-side row in both years'
segment tables as "descriptive only, n<30, not powered for a directional claim."

### [W3] Historical process violation: a Stage-2 2026 run occurred before Stage 1's gate was finalized and before any clean 2025 predecessor existed — caught and superseded, but the code-enforced gate postdates the violation

Timestamps (file mtimes, `_snapshots/` and `audit/` folders):

- `_snapshots/stage2_broken_direction_20260713_1335/stage2_trades_2026.parquet` etc. —
  **13:35:55**.
- `evaluate_stage1.py` (independent Stage-1 gate evaluator) created — **13:41:55**.
- `results/stage1_gate.json` (final, corrected Stage-1 gate decision) — **13:42:06**.
- `run_stage2_ohlc.py`'s `require_clean_2025_predecessor()` hard-gate (the code that now
  *prevents* a 2026 run without a same-hash, zero-error 2025 reconciliation) — introduced in
  the version of the file written at **13:40:17**.

The 13:35:55 2026 run therefore executed (a) before Stage 1's gate was independently
confirmed PASS on corrected data, and (b) before any code-enforced "2025 must complete
cleanly first" gate existed — i.e., under an earlier version of the pipeline that did not
yet have the `require_clean_2025_predecessor` assertion later added. This is exactly the
chronology SPEC.md's "hard" rule and the Stage-2 pre-execution audit's "2025-before-2026
sequencing" check exist to prevent. Per the same evidence in W1/W2 above, this particular
2026 run happened to be numerically immaterial (2026's atlas `direction` was never affected
by the C1 bug), so no information leaked into any tunable parameter — the frozen policy hash
(`e290fe07...`) is identical across every artifact touched, before and after. But the
*process* still violated the hard chronology rule at the time, before the fix made the
code self-enforcing.

**Recommendation (do not apply):** no code change needed retroactively (the current
`require_clean_2025_predecessor()` gate already prevents recurrence), but this incident is
worth recording in the study's own audit trail as a resolved process finding, not silently
dropped.

### [W4] `final_report.md` and `stage2_frozen_policy.json` disclose the pre-fix "139s" descriptive rationale artifact but not the deeper direction-source defect or its 2025 trade-count impact

`stage2_frozen_policy.json:14` ("`filter_rationale`") and `final_report.md`'s Reconciliation
section both disclose that the 120s filter threshold's rationale text cites a pre-fix
"139s" 2025 descriptive median (vs. the corrected 142s), and correctly note this did not
change any frozen parameter. That disclosure is good practice. However, neither artifact
discloses that the underlying 2025 Stage-2 **trade population itself was regenerated** after
a direction-source defect affected 34.66% of the originally-produced 2025 trades (a materially
larger fact than the 139s→142s rationale-text drift). A reader of `final_report.md` alone,
without reading `audit/completion_audit.md` or the pre-execution audit's "Loader re-audit"
addendum, would have no way to know the headline 2025 numbers (+$5.11/tr, PF 1.034,
2,103 trades) supersede an earlier, materially different run (2,403 trades) that was
discarded for cause.

**Recommended fix (do not apply):** add one line to `final_report.md`'s Reconciliation
section noting that the 2025 Stage-2 population was rebuilt after a regime-direction-source
defect was found and fixed (cross-reference `audit/completion_audit.md` and the loader
re-audit), distinct from the already-disclosed cosmetic rationale-text drift.

---

## NOTES

### [N1] `FLIP_ATLAS` is imported but never used in both `build_stage1.py:19` and `run_stage2_ohlc.py:16`

Dead import in both files, left over from the pre-fix code paths that read
`flip_context_atlas` directly for direction. Already flagged as non-blocking in the
Stage-2 pre-execution audit's "Loader re-audit" section. Confirmed still present. No risk
today (nothing reads it), but worth removing next time either file is touched, per the
existing recommendation.

### [N2] `stage1_regime_metrics.parquet`'s `close` → `start_close` column is loaded (`build_stage1.py`) but never referenced downstream

Already flagged clean/non-blocking in `audit/pre_execution_lookahead_audit.md` ("harmless
dead column, not a leak"). Reconfirmed by this audit — no change in status.

### [N3] No genuinely-broken 2026 Stage-2 snapshot exists to independently corroborate the C1 fix's (lack of) impact on 2026

Because the atlas's `direction` column was already 0%-NaN for 2026 (unlike 2021-2025), the
C1 defect structurally could not have manifested there, and the only preserved 2026 "broken"
snapshot is — as W1 shows — essentially identical to the fixed output. This makes the
2026 side of the fix un-falsifiable from artifacts alone (there is nothing to compare
against that would show a difference if the fix mattered). The independent re-derivation
in `run_stage2_ohlc.py`'s own fail-fast parity assert (0/8,922 mismatches against
`causal_scores.parquet` direction, per the Stage-2 pre-execution audit's "Loader re-audit"
section) is the only real evidence for 2026 correctness, since no cross-check against
Stage-1 metrics is possible for 2026 (Stage 1's chronology firewall never touches 2026 data
by design). This is inherent to the study's own 2026-firewall design, not a gap introduced
by the fix — noted for completeness, no action recommended.

---

## Verification performed for this audit (detail)

### 1. Reconciliation cleanliness, policy hash, post-fix provenance

- `results/stage2_reconciliation_2025.json` / `_2026.json`: both `blocking_errors: 0`,
  `closure_residual: 0`, `exit_reason_residual: 0`, `policy_sha256` ==
  `e290fe0726a309295b930eaeeba6cc491fd68cb21c186fd05cb4d55529fc8e7d` == SHA-256 of both
  `stage2_frozen_policy.json` (root) and `_snapshots/stage2_frozen_policy.json` (identical
  bytes, confirmed via `certutil -hashfile`).
- File mtimes: `run_stage2_ohlc.py` (fixed, fresh-engine `load_regimes()`) — 13:40:17;
  `results/stage2_reconciliation_2025.json` — 13:49:29; `results/stage2_reconciliation_2026.json`
  — 13:50:02. Both postdate the fix. `run_stage2_ohlc.py:main()` additionally hard-asserts
  `require_passed_audit()` (checks `audit/stage2_pre_execution_audit.md` for
  `**Status:** **PASS` and `0 CRITICAL`/`0 WARNING`, both present) and, for 2026 only,
  `require_clean_2025_predecessor()` (same-hash, zero-error, closed 2025 reconciliation) —
  both gates are satisfied by the artifacts on disk today.

### 2. `analyze_stage2.py` decision logic is mechanical

`analyze_stage2.py:94-98`:
```python
if y25.mean_net_pnl_usd > 0 and y26.mean_net_pnl_usd > 0 \
        and y25.profit_factor > 1 and y26.profit_factor > 1:
    decision = "PROMISING_NEEDS_FULL_VALIDATION"
else:
    decision = "NO_MONETIZABLE_WEAKNESS_FADE"
```
Reads directly off `stage2_policy_results.parquet` (itself computed straight from the
per-trade parquets, `analyze_stage2.py:metrics()`). 2026's `mean_net_pnl_usd = -12.43 < 0`
and `profit_factor = 0.931 < 1` independently force `NO_MONETIZABLE_WEAKNESS_FADE` — no
2026-conditioned branch, threshold, or override exists anywhere in `analyze_stage2.py`,
`run_stage2_ohlc.py`, or `stage2_frozen_policy.json`. `stage2_frozen_policy.json`'s only
free-text rationale field (`filter_rationale`) cites only 2021-2024 and a 2025 sanity value
("139s"), never a 2026 number. Confirmed clean.

### 3. Stage2_trades_2025.parquet spot checks (5 randomly sampled rows, manually recomputed)

For each sampled row: `entry_direction == -prevailing_direction` (exact, all rows);
`stop_px = entry_fill_px - entry_direction * 1.5 * atr_at_trigger` reproduced to full
float precision; `realized_stop_atr == 1.5` exactly; `gross_pnl_pts = (exit_fill_px -
entry_fill_px) * entry_direction`, `gross_pnl_usd = gross_pnl_pts * 20`, `net_pnl_usd =
gross_pnl_usd - 10` all reproduced exactly; `hold_s`/`entry_fill_delay_s` arithmetic
reproduced exactly from the nanosecond timestamp columns. Entry/decision timestamp ranges
for the full 2025 and 2026 trade files fall entirely inside their authorized windows
(`2025-03-03 .. 2025-12-30` ⊂ `[2025-03-01, 2025-12-31)`; `2026-01-02 .. 2026-04-29` ⊂
`[2026-01-01, 2026-04-30)`). `stop_after_flip` rows (124 in 2025, 56 in 2026) all satisfy
`entry_fill_ts < confirm_flip_ns <= exit_fill_ts` (checked on the full column, not just the
sample). No arithmetic or window violation found.

### 4. Direction asymmetry — see Warning W2 above for full detail and root-cause attribution.

Independent regime-direction cross-check performed for this audit (not previously
documented in any prior audit artifact): joined all 2,103 `results/stage2_trades_2025.parquet`
rows to `results/stage1_regime_metrics.parquet` (`period=="validation"`) on
`regime_start_ns` — two separate code paths (`build_stage1.py`'s and
`run_stage2_ohlc.py`'s independent fresh-per-year `aggregate_and_run_regimes` calls) agree
on `direction` for **all 2,103/2,103** matched rows, 0 mismatches. This is in addition to,
and independent of, `run_stage2_ohlc.py`'s own internal fail-fast parity check against
`causal_scores.parquet`.

### 5. Stage-1 gate artifact consistency

`results/stage1_gate.json` (`analyze_stage1.py`) and `audit/stage1_gate_evaluation.json`
(`evaluate_stage1.py`, an intentionally separate/independent implementation) both read from
the same `results/stage1_regime_metrics.parquet` and produce numerically identical values
for every compared field (train `winner_count` 28,789 == 28,789; `paired_w4_n` 20,551 ==
20,551; validation `winner_count` 7,147 == 7,147; `paired_w4_n` 5,042 == 5,042; decision
`ESTABLISHED_REGIME_FILTER_FOUND` == `ESTABLISHED_REGIME_FILTER_FOUND`). Both postdate the
Stage-1 direction fix: `results/stage1_regime_metrics.parquet` (the shared input) was
written at 13:38:45, after `audit/stage1_regime_source.json` (13:37:33, documenting the
fresh-RegimeEngine repair) and before both gate artifacts (13:42:06 / 13:42:08). Compared
against the pre-fix `_snapshots/results_20260713_1340/stage1_gate.json`: the pre-fix train
split shows `winner_count=37,112`, `peak_mfe_ratio=1.80`, `progress_windows_delta=0.0`
(**a structural condition that fails**, dropping to 3/4 conditions passed) — materially
different from the corrected `winner_count=28,789`, `peak_mfe_ratio=2.70`,
`progress_windows_delta=1.0` (4/4). Both pre- and post-fix Stage-1 gates happen to reach the
same `ESTABLISHED_REGIME_FILTER_FOUND` decision (3/4 vs. 4/4, both ≥ the predeclared minimum
of 3), but the underlying population/metrics genuinely changed by a large margin, confirming
the Stage-1 fix was substantive (unlike Stage 2's 2026 side, which barely moved).

---

## Clean checks

- Stage-2 stop/touch fill logic uses bar `low`/`high` for stop detection
  (`run_stage2_ohlc.py:299`), not `close` — no Section-H bar-mode-overstatement risk.
- Gap-through handling: a stop-active bar whose own `open` already exceeds the stop level
  fills at that bar's open, not at the nominal trigger price (`run_stage2_ohlc.py:301-302`)
  — satisfies H4.
- Temporal resolution: stop/touch detection iterates 1-second bars for both years,
  consistent with the policy's own "1-second OHLC research simulation" label — no
  coarser-checkpoint understatement risk (H2 n/a here since there is no separate NT-native
  comparison being claimed).
- Entry price uses the actual next available raw-bar open (`searchsorted` + `opens[entry_i]`),
  never the decision/signal price — no entry-price look-ahead.
- Filter fields (`regime_age_s`, `running_mfe_atr`, `new_progress_windows`, `retained_mfe_ratio`)
  are computed as strict prefixes up to the decision index `k` (`run_stage2_ohlc.py:166-198`)
  — no future bar enters the live filter.
- W4 crossing requires strict `prev_score < threshold <= score` and decision timestamp
  `observation_time + 1s`, matching causal availability — no same-bar or backward-looking
  trigger.
- 2026 firewall: `require_clean_2025_predecessor()` and `require_passed_audit()` both
  enforced in code before any 2026 write; both currently satisfied.
- Policy hash identical across `stage2_frozen_policy.json` (root) and its `_snapshots/` copy,
  and identical on every trade row in both years' output — no post-hoc parameter tuning
  possible without detection.
- Overlap/busy-until state machine keyed on decision time, not delayed fill time — no
  signal generated while busy can queue for a later entry.
- Censored/data-end handling: final open regime retained, right-censored, no fabricated
  future exit — verified via `exit_reason` distribution (`data_end_censored: 0` in both
  years' current reconciliation, i.e. no trade in the finalized set was left in a
  censored/incomplete state, consistent with the study period ending mid-regime for very few
  or no still-open positions at each window's close).

---

*Audit complete. This report is intended to supersede `audit/completion_audit.md`'s FAIL
status for the specific C1 defect it identified — that defect is verified fixed by two
independent means (Section 4) — but a documentation update to `completion_audit.md` itself
(or an explicit cross-reference from it) is recommended so the audit trail is not left with
a dangling FAIL statement. The one CRITICAL and four WARNING findings above are otherwise
process/disclosure gaps, not numerical corruption: reconciliation, decision logic, fill
timing, stop/target mechanics, and chronology firewalls all check out on direct
re-verification.*
