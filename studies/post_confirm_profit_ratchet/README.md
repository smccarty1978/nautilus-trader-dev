# post_confirm_profit_ratchet

**Verdict: D — GEOMETRY SEPARATES BUT ECONOMICS DO NOT.** The profit-ratchet
hypothesis is **not supported**. Read `REPORT.md` for the argument, `SPEC.md` for
the frozen contract.

## The question

The predecessor (`post_confirm_forward_opportunity`, verdict E) established that
after a trade earns a favorable rung, `P(next +0.50 ATR)` is **0.79–0.81 at every
rung** — a memoryless ladder — while mean peak-to-terminal giveback is ~2.14 ATR.
*Harvesting* on that ladder paid nothing. This study asked the different question:
can a **ratcheting stop** protect part of the achieved profit while preserving most
of the trades that would have reached the next rung?

## The answer

No, and for a structural reason rather than a tuning one:

- Successful continuation requires **median 0.55 / p90 ~1.5 ATR** of high-water
  retracement, and that requirement is **flat across rungs** — earning 4 ATR buys
  no reduction in the room the next 0.5 ATR demands.
- Measured to their own terminals, **successful continuations draw down further
  from their high-water mark (2.35–2.75 ATR) than failed ones (1.97–2.36 ATR)**,
  because they live ~2.8× longer.
- The apparent separation (raw AUC **0.96–0.97**) is almost entirely trade
  duration; on matched elapsed windows it collapses to **0.56–0.75**.
- **0 of 126** frozen cells clear the decision gate. Best cell recovers **1.73%**
  of the 0.898 ATR/entry giveback pool, CI spans zero, effectively short-only.

Loss containment (~0.20 ATR/entry) is cancelled almost exactly by runner
destruction (~0.20 ATR/entry) at every rung and stop distance tested.

## Reproduce

```bash
python scripts/causal_lint.py --study studies/post_confirm_profit_ratchet \
    --json studies/post_confirm_profit_ratchet/audit/lint.json
python -m studies.post_confirm_profit_ratchet.implementation.build      # ~2.5 min
python -m studies.post_confirm_profit_ratchet.implementation.validate   # 16 gates
python -m studies.post_confirm_profit_ratchet.analysis.phases           # all tables
python -m studies.post_confirm_profit_ratchet.analysis.examples         # Phase 8
python -m studies.post_confirm_profit_ratchet.analysis.close_out        # summary.json
```

Set `PYTHONIOENCODING=utf-8` on Windows; polars table printing fails under cp1252.

## Layout

```
implementation/rungs.py     rung events, transitions, stop surfaces, policies
implementation/build.py     the three panels + partition manifest
implementation/validate.py  the 16 SPEC §9 gates, incl. hard-truncated replay
analysis/phases.py          every reported table, the decision gate
analysis/examples.py        Phase 8 path exhibits (frozen selection rules)
analysis/close_out.py       summary.json and the mechanical label routing
```

Key outputs: `results/master_tradeoff.csv` (the tradeoff table),
`results/summary.json` (the eight answers + label),
`results/validation_report.json` (gates), `results/decision_gate.csv`.

Four artifacts are intermediate/derived rather than Deliverables-Manifest rows:
`results/trade_panel.parquet` (per-trade constants consumed by the gates),
`results/path_examples_index.{csv,parquet}` (the frozen Phase 8 selection, split
out from the path table), and `results/gate_verdict.json` (the gate's own
machine output, summarised into `summary.json`).

## Contract notes

- Population, giveback pool (0.8980826) and baseline (−0.0765296) reproduce the
  accepted study **exactly**; the `FROM_ENTRY` ladder matches to 7 decimal places.
- **2026 sealed and never read.** **2025 is NOT threshold-OOS** (inherited waiver).
- Primary rung basis is `POST_CONFIRM` (arming clamped to the confirmation bar);
  `FROM_ENTRY` is carried for lineage. Both `ARM_FRESH` and `ARM_AT_CONFIRM`
  strata are reported everywhere.
- `runner_survival` at a tier **at or below** the arming rung is **tautological**
  (a ≥T runner necessarily reaches the T rung and is alive at that touch by
  construction). Only tiers strictly above the arming rung are informative — this
  is why `runner_survival_3atr` reads 100% at rungs 3.0 and 4.0.
- `auc_raw_DURATION_CONFOUNDED` is named for what it is and is never quoted alone.
- Three placebos: `P_BLIND` (length-blind, causally implementable), `P_UNCOND`
  (armed at confirmation), `P_UNIFORM` (**FUTURE_INFORMATION**, benchmark only).
