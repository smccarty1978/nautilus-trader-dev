# Completion audit: authorized OHLC full policy matrix

Date: 2026-07-12  
Status: **PASS — AUTHORIZED OHLC STUDY COMPLETE**

**CRITICAL: 0**  
**WARNING: 0**

The simulation artifacts, core accounting, and regenerated final report reconcile cleanly. The reporting-only findings from the first completion pass are resolved; the matrix was unchanged.

## Reconciliation performed

### Population and contracts

- `trade_results.parquet`: **407,261** rows; **407,257** complete and **4** data-end censored.
- Contracts: 203,717 primary explicit-next-open rows and 203,544 Contract 3 sensitivity rows.
- Years: 291,568 rows for 2025 and 115,693 for 2026.
- Policies: P0/P1/P2/P3/P4A/P4B all present.
- Stop grid is exactly **0.50, 1.00, 1.50 ATR**; P0/P2 have no stop grid.
- Exit reasons reconcile to exactly one status per row:
  - opposite flip: 134,733;
  - stop before flip: 123,944;
  - D10 exit: 102,454;
  - stop after flip: 46,126;
  - data-end censored: 4.

### Accounting and lifecycle invariants

- `pre_flip_pnl + post_flip_pnl == gross_pnl`: maximum absolute error **0.0**.
- `net_pnl == gross_pnl - $10`: maximum absolute error **0.0**.
- Censored rows with an exit price: **0**.
- Completed rows missing exit time or price: **0**.
- Negative entry delays: **0**.
- Pre-flip entry decision at/after confirmation: **0**.
- Incremental D10 PnL populated on non-D10 exits: **0**.
- `exit_reason_completeness_audit`: 407,261/407,261 pass.
- `position_overlap_audit`: 407,261/407,261 pass.
- `score_regime_id_audit`: 407,261/407,261 pass.
- Policy trade-count reconciliation maximum difference: **0**.
- A stratified sample of 28 raw-path trades across contracts/reasons/years matched the expected primary open or Contract 3 prior-close entry, fill-anchored stop formula, gross PnL, and costs with **0 errors**.

### Timing and gap transparency

- Exact-boundary rows: 295,449.
- Short market-data gaps (1–60s): 111,162.
- Extended gaps (>60s): 650.
- Extended gap maximum: 262,029 seconds in 2025 and 176,400 seconds in 2026.
- Class-level gap counts/minimum/median/maximum are present by contract/year.
- Same-bar stop/logical-exit ties: **1,815**, all retained in the audit; D10/flip equality count is zero in this sample.

### Coverage and D10 attribution

- Regime coverage: 31,844 regimes (22,910 in 2025; 8,934 in 2026).
- Validly scored: 31,810; causally reached D10: 24,805 (**77.98%**).
- Score unavailable: 34; duplicate regime IDs: 0; causally invalid reached rows: 0.
- D10 contribution rows: 219,601, classified as:
  - stopped before D10: 81,387;
  - D10 improved PnL: 71,262;
  - D10 reduced PnL: 31,192;
  - opposite flip before D10: 26,871;
  - D10 never occurred: 8,689;
  - score unavailable: 200.
- D10 rows with invalid incremental attribution: 0.
- Confirmed-trade availability: 112 breakdown cells; all percentages within [0,1].

### Decomposition, controls, and outputs

- PnL decomposition: 296,825 rows; component error 0; negative MAE rows 0; USD/points multiplier error 0.
- Matched placebo: 24 required cells, each with pairs; paired count range 598–2,841; 38,285 paired rows.
- Fixed-seed sign-randomization p-value range: 0.0003999–0.0845831.
- Executed balance: 48 rows, all finite; maximum absolute SMD 0.2149.
- Design balance: 8 rows, all finite; maximum absolute SMD 0.4184.
- Monthly grids contain 10 months per 2025 cell and 4 per 2026 cell; stop-sensitivity contains exactly three stops per required cell.
- Required manifest files exist and are nonempty; schema audit passes; missing core policy cells: 0.

### Primary result and selection discipline

- No threshold, stop, or policy was selected using 2026.
- All six primary P1/P3 stop cells have negative EV lift versus P0 in 2025: **-8.1342 to -3.7615**.
- All six have positive lift in 2026: **16.0856 to 21.3184**.
- The `CLOSE` conclusion is directionally supportable because the required both-period continuation condition is not met and the result is unstable across years. This conclusion remains an OHLC research result, not executable validation.

## Initial completion finding — resolved

### Resolved C1 — Headline pre/post/front-run averages mixed real, placebo, primary, and sensitivity populations

Files: `finalize_ohlc_report.py`, `results/final_report.md`

The finalizer reads the entire `pnl_decomposition.parquet` and computes headline means without filtering contract or policy. The reported values therefore combine P1/P3 real trades, P4A/P4B placebo trades, the primary contract, and Contract 3 sensitivity:

```text
reported all-row averages:
pre-flip PnL          -$6.72
post-flip PnL         -$5.60
front-run advantage  -$15.22 (-0.091 ATR)
```

For the primary real strategy population only (`EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT`, P1/P3), the audited values are materially different:

```text
primary P1/P3 averages:
pre-flip PnL          +$0.44
post-flip PnL         -$5.23
front-run advantage   -$1.82 (-0.0178 ATR)
```

The sign of average pre-flip PnL changes. This can materially alter the diagnosis of whether the failure comes from the pre-flip burden or post-flip management. Placebos and sensitivity results must never be silently pooled into primary headline economics.

Resolution: the finalizer now freezes primary P1/P3 as the headline population, reports placebo and Contract 3 separately, and regenerates the report with the corrected values documented below.

## Initial completion warnings — resolved

### W1 — Verdict code tests an overbroad policy set and incomplete CONTINUE criteria

File: `finalize_ohlc_report.py`

The `qual` table is built from every non-P0 primary policy, including P2 and placebo P4 policies, and `CONTINUE` requires only positive EV lift in both years. The user-defined CONTINUE rule also requires acceptable stop rate, positive front-run advantage after costs, superiority to placebo, tail independence, drawdown, and clean audits. A placebo policy could theoretically trigger CONTINUE.

The present `CLOSE` result is still supported because all real P1/P3 2025 lifts are negative, but the decision code is unsafe and the recommendation narrative is too terse.

Resolution: verdict candidates are restricted to primary P1/P3, no stop is selected, and the absence of any both-year positive-lift cell yields CLOSE.

### W2 — Extended gap exposure is absent from the final report failure modes

File: `results/final_report.md`

The artifacts transparently classify 650 extended-gap rows, including gaps up to roughly 72.8 hours. The final report does not state their count or maximum, even though it discusses execution limitations. These are authorized first-next-available fills, but weekend/holiday exposure is material context.

Resolution: the final report discloses 650 extended-gap rows and the 262,029-second maximum, while class-level details remain in the timing audit.

### W3 — Material placebo imbalance is not discussed

Files: `results/final_report.md`, `results/matched_placebo_balance.parquet`, `results/executed_pair_balance.parquet`

The report points to artifacts but does not disclose that maximum absolute standardized mean difference is approximately 0.418 at design stage and 0.215 in executed pairs. This does not invalidate the fixed-seed comparison automatically, but it limits causal interpretation of the placebo p-values.

Resolution: the final report discloses both maximum balance statistics and makes no randomized-control claim; pair counts and attrition remain in the matched artifacts.

## Reporting repair verification

- Headline decomposition is now filtered to the primary `EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT` and real P1/P3 policies only.
- Regenerated headline values reconcile to that population:
  - average pre-flip PnL: **+$0.44**;
  - average post-flip PnL: **-$5.23**;
  - average front-run advantage: **-$1.82 (-0.018 ATR)**.
- Placebo and Contract 3 rows no longer contaminate primary headline economics.
- Lift/verdict candidates are restricted to primary P1/P3. No policy/stop is selected; because no P1/P3 stop cell has positive lift in both years, the report returns **CLOSE**.
- The report explicitly states the headline population and retains the unchanged 2025/2026 lift ranges.
- Extended-gap exposure is disclosed: **650** trade rows and maximum delay **262,029 seconds**, with class-level details in the timing audit.
- Matched-control balance is disclosed: maximum absolute design SMD **0.418** and executed-pair SMD **0.215**. The report makes no randomized-control or executable-validation claim.
- The final report was regenerated after the matrix, and the repaired values match direct parquet recomputation.

## Completion gate

**PASS.** The authorized OHLC research study is complete with zero remaining critical or warning findings. The verdict is **CLOSE** as a research conclusion only; no NT-native executable validation or test-set parameter selection is claimed.
