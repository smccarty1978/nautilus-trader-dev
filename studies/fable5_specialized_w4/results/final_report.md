# FABLE5 — CODEX 5.X W4 Specialized Model Study

## Decision

**`SPECIALIZATION_OVERFITS_2025`** (and, equivalently for deployment,
**`NO_SPECIALIZED_W4_EDGE`**)

Training W4 candidate selection separately by side, and by side×session,
produces an apparent development edge that does **not** survive to the
selection-isolated 2026 holdout. Every specialized arm loses money in 2026,
and none beats the current pooled/frozen Policy A baseline in either year.
The strongest development arm (`B_side`, ~10% retention) earns **+$21,604**
on 2025-H2 development and **inverts to −$18,869** on 2026. The
frozen-model ranking (`baseline_w4`) is no better. The signal the models
learn is a thin, non-stationary artifact, not executable trade selection.

This is a **1-second OHLC research simulation**, not NT-native executable
validation. Sample depth is limited (2025-only training), so 2026 is a
selection-isolated descriptive test, not deployment approval. It does not
need to be: the result is negative.

## What was built and verified

- **Population:** the audited 11,812 strict-crossing candidates in 4,767
  opportunities (8,682/3,530 in 2025, 3,130/1,237 in 2026), reused unchanged
  from the multi-candidate study. 8,666/2025 and 3,126/2026 are replayable.
- **Labels:** every candidate replayed **independently** from its immediate
  causal fill under the byte-identical frozen Policy A management contract
  (1.25 ATR pre-flip stop, 300s timeout, 1.50 ATR post-flip stop,
  opposing-flip exit, $10 RT, $20/pt). The array port of `simulate_trade`
  is proven behaviorally identical to the upstream by 7 fixture parity cases.
- **Reconciliation gate (passed exactly, both years):** seq-1 candidates on
  the frozen executable regime set reproduce the frozen Policy A trades to
  the cent — 3,246 trades / −$8,114.842750573298 in 2025, 1,137 trades /
  +$17,988.060996803324 in 2026, zero mismatches on entry/exit ts, price,
  reason, and PnL.
- **Split discipline:** train 2025-H1 (4,501 rows after boundary purge),
  select config on 2025-H2 (4,163 rows), 2026 sealed behind a frozen manifest
  and first-open ledger. Completion audit independently confirmed zero
  `opportunity_id` overlap between train and dev and zero 2026 references in
  any frozen artifact.
- **Models:** A pooled, B side-specific, C side×session (all four cells had
  adequate sample — no `INSUFFICIENT_SAMPLE`), D hierarchical isotonic on the
  frozen `w4_score`, plus the frozen `score_margin` baseline. Logistic and
  HistGBT families, config chosen on H2 top-30% independent economics only.
- **Audits:** pre-execution lookahead audit PASS (0 CRITICAL, 0 WARNING);
  completion audit 0 CRITICAL, 1 WARNING (cosmetic — see caveat below).

## Headline economics (independent candidate accounting, net $)

| Arm | actual retention | 2025-H2 dev | 2026 test |
|:--|--:|--:|--:|
| **Current baseline — `policy_a_frozen`** | 38% | **−18,970** | **+17,988** |
| take-all candidate stream | 100% | −83,260 | −42,650 |
| `A_pooled` top-10% | ~10% | −10,832 | −18,433 |
| `B_side` top-10% | ~10% | **+21,604** | **−18,869** |
| `B_side` top-30% | ~30% | −6,619 | −33,505 |
| `C_side_session` top-10% | ~10% | +4,666 | −15,444 |
| `baseline_w4` (frozen) top-20% | ~26% dev / 25% '26 | −24,941 | +3,974 |
| `D_hier` isotonic | 60–77% | −40,258 | −2,037 |

The only arm that is positive in 2026 is the **current frozen Policy A
baseline itself** (+$17,988), which no retrained or specialized model
matches. Among specialized models, `B_side` top-10% is the single most
promising development result and the clearest failure out-of-sample: a
$40K swing between dev and test on ~10% retention.

One-position streaming accounting tells the same story more mildly (lower
exposure shrinks the losses but never turns any specialized arm positive in
2026); the two accountings agree on sign and ranking throughout.

## Model diagnostics (do not override the economics)

- **AUC:** dev ROC-AUC 0.49–0.53 across structures, falling to **0.47–0.49
  in 2026** — at or below chance out-of-sample. `A_pooled` long-fade is the
  best dev segment (0.571) and still decays to 0.530 in 2026.
- **Calibration inverts in 2026:** in the confident deciles, higher predicted
  net-positive probability maps to *worse* realized PnL (e.g. `B_side` pred-bin
  8 realizes −$608/trade; `A_pooled` pred-bin 6 realizes −$275/trade). See
  `specialized_w4_calibration_report.md`.
- **In-sample memorization:** on H1 the GBTs report +$499K (B_side top-10%,
  94.6% win rate) — a pure overfit signature that collapses to +$21.6K on H2
  and −$18.9K on 2026. This is why config selection was done on H2, not H1.
- **Feature importance / stability** (`specialized_w4_feature_importance.parquet`):
  no stable dominant predictor; single-feature monthly AUCs on H1 are close to
  0.5 and unstable in sign, consistent with the OHLCV-ceiling findings in prior
  W4 work.

## Answers to the study's nine questions

1. **Does long/short separate training improve economics?** No. `B_side`
   beats `A_pooled` on dev but both lose in 2026; neither beats the baseline.
2. **Does side/session help beyond side-only?** No. `C_side_session` ≈
   `B_side` on dev and is also negative in 2026; extra segmentation adds
   variance, not edge.
3. **Stable across 2025 and 2026?** No. The sign flips between windows for
   every specialized arm — the defining failure.
4. **Does long ETH stop being the drag?** No. `B_side` long-ETH is barely
   positive on dev (+$899, ~7$/trade) and −$9,465 in 2026. The apparent
   improvement is exposure reduction, not selection: the baseline take-all
   long-ETH is roughly flat both years, so trimming it neither reliably helps
   nor is the source of any edge.
5. **Is short RTH preserved?** No — it is damaged. Under `B_side` top-30%,
   short-RTH is −$22,934 on dev and −$12,453 in 2026; the models
   preferentially *keep* short-RTH candidates that then lose. The frozen
   baseline's short-RTH (+$4,199 dev / +$6,709 '26) is better untouched.
6. **Does model selection improve win rate materially?** No. Executed-trade
   win rate moves only within ~0.28–0.40 across bands and is not stably above
   the ~0.31 take-all rate out-of-sample.
7. **Does PnL/trade improve beyond a few dollars?** Only in-sample and on the
   thin dev top-10% band (+$52/trade, B_side); it is negative per trade for
   every specialized arm in 2026.
8. **Real ranking power or just lower exposure?** Neither produces edge. Dev
   band monotonicity shows *some* ranking, but AUC ≤0.53 dev / ≤0.49 '26 and
   the 2026 calibration inversion show it is not real out-of-sample. Lower
   exposure only shrinks losses.
9. **Next research branch?** The candidate-time OHLCV feature set has no
   monetizable side/session-specific structure the pooled W4 was missing.
   Do **not** pursue further W4 model specialization on this feature family.
   If W4 is revisited, it requires a genuinely new information source
   (order-flow / microstructure), i.e. the `FULL_COLLECTOR_V2_REQUIRED`
   direction — not more slicing of the existing atlas.

## Comparisons requested

- vs **current pooled W4 Policy A baseline**: baseline wins outright (+$17,988
  in 2026 vs every specialized arm negative).
- vs **prior R10 first-crossing / multi-candidate R10**: R10 was +$4,527 vs R0
  combined but −$11,265 in 2026; specialized selection is worse than R10 in
  2026 and also unstable.
- vs **streaming S1/S4**: S1/S4 were already rejected (`REENTRY_ADDS_CHURN`);
  the one-position streaming arm here is likewise negative in 2026.
- The central comparison — *does specialization keep short/RTH while rejecting
  long/ETH garbage?* — is answered **no**: it damages short-RTH and does not
  convert long-ETH.

## Caveats and evidence boundary

- **Completion-audit WARNING (cosmetic):** `D_hier` isotonic output and
  `baseline_w4` `score_margin` have tied plateaus, so some retention *band
  labels* accept identical sets (`D_hier` top-20…top-50 all ≈77% retention;
  `baseline_w4` top-50 ≈78%). The `retention_rate` column is correct and all
  economics are correct — always read the actual `retention_rate`, not the
  band label, for these two structures. Structures A/B/C are unaffected.
- 2025-H2 was the frozen W4's isotonic calibration window, so candidate
  *membership* is mildly in-sample for H2 (declared in SPEC). This only makes
  the dev numbers optimistic; it does not rescue 2026.
- Stop fills at the exact trigger on non-gap bars (inherited from the frozen
  Policy A contract) — a small optimism, identical across all arms and the
  baseline, so it does not affect the comparison.
- No 2026 quantity influenced any model, threshold, retention rule, segment
  choice, or feature set. The positive `baseline_w4` 2026 blip and any
  favorable cell are retrospective diagnostics, not selected policies.

The Parquet deliverables are authoritative for every candidate, label, model
metric, decile, calibration bin, policy split, and reconciliation figure.
