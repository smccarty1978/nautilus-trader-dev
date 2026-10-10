# nq_fair_pricing_reversion — TRAIN Collection & Outcome Audit Report

## 1. Collection Integrity
The full 2021–2023 TRAIN population has been reconciled:
- 69,369 candidates over 772 trading sessions across partitions 2021 (23,088), 2022 (23,196), and 2023 (23,085).
- Every arm satisfies positive + negative + censored = total.
- The merged artifact matches the three annual partitions row-for-row (
econcile.json status: PASS).

## 2. Outcome Semantics & Cadence
- Barriers resolve causally on 
q_1m completed bars.
- 
esearch_workflow/grammar/compiler.py:1260 binds the outcome stream to the population cadence (completed_1m).
- OutcomeSpec has no stream override field in the declarative grammar.

## 3. Bounded Outcome Parity & Forensic Audit
- Governed 1-second replay of 2,427 candidates across 27 sessions confirms:
  - 0 target-vs-stop sign reversals and 0 censoring status alterations.
  - Labels changed only for rows that 1-minute bars had censored as same-minute ambiguous (31 of 31 tp38 rows, 29 anchor rows).
- Root-cause forensic localization on October 12, 2023:
  - At 10:27 ET, market high breached the adverse stop (,448.50$) with a high of ,461.00$ ($+12.50$ pts).
  - The observational multi-arm composite kernel masked this adverse touch because shared recovery arms set rm_bad = +inf. Real-time event execution terminates the trade at 10:27 ET as expected.
- Root-cause forensic localization on October 30, 2023:
  - Trade #12 reached its 38 pt profit target on the 1s tape at 10:02:48 ET.
  - The strategy was flat when Signal #13 completed at 10:03:00 ET, allowing valid causal order entry.

## 4. Retained Evidence Manifest
- Raw Parquet partitions and merged outputs remain durably retained on disk under _work/controller/.
- Cross-agent audit verification logs are persisted in studies/nq_fair_pricing_reversion/audit/train_evidence/.
