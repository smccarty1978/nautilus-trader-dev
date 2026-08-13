# post_confirm_forward_opportunity

Forward opportunity / continuation-value map for the post-confirmation phase of
the accepted immediate Top-10 fade population. **Not** an exit-policy study —
it is the optimal-stopping prerequisite that was missing before one.

**Verdict: `E — PRICE STATE HAS FORWARD INFORMATION BUT NOT ENOUGH FOR ECONOMIC
ACTION`.** See `REPORT.md`.

---

## What this answers

> After the confirming regime flip, at any causal observation time `t`: what is
> the probability and expected value of additional favorable movement versus
> adverse movement **from the current price**?

One-line answer: the causal state predicts the **scale** of what remains, never
its **sign**. Forward MFE and forward MAE decay together (ratio 1.13–1.26 across
every stall bucket), `P(+0.50 before −0.50)` on resolved races is 0.49–0.52 in
every one of 220 candidate state regions, and `E[continue − exit now]` has a
trade-clustered 95% CI spanning zero in **all 79** trade-level buckets.

---

## Layout

```text
SPEC.md      frozen 2026-08-11 before implementation; D1-D9 are the causal contract
REPORT.md    Q1-Q16 + final classification
implementation/
  engine.py       observation states (prefix [0..j]) and forward labels (suffix [j+1..])
  geometry.py     Phase 11 placebo diagnosis, Phase 12 harvest geometry
  build.py        writes the five panels
  validate.py     the 14 SPEC 9 gates
analysis/
  buckets.py         frozen bucket edges + the shared metric block
  phases.py          Phases 0-13 -> the deliverable tables
  gate.py            Phase 14: 220 candidate regions x 8 conditions
  harvest_control.py Phase 12 control (placebo on the rung ladder)
  close_out.py       assembles summary.json from the written tables
tests/         26 deterministic tests on synthetic windows
audit/         lint.json, pass_01.md, status.json, contract_status.json
results/       parquet + CSV mirrors
```

## Reproduce

```bash
python -m studies.post_confirm_forward_opportunity.implementation.build          # ~17 s
python -m studies.post_confirm_forward_opportunity.analysis.phases
python -m studies.post_confirm_forward_opportunity.analysis.gate
python -m studies.post_confirm_forward_opportunity.analysis.harvest_control
python -m studies.post_confirm_forward_opportunity.implementation.validate
python -m studies.post_confirm_forward_opportunity.analysis.close_out
python -m pytest studies/post_confirm_forward_opportunity/tests -q
python scripts/causal_lint.py --study studies/post_confirm_forward_opportunity
```

## Substrate

Inherited unchanged from `top10_fast_confirm_runner_path` (verdict C). No
recollection, no new features, no model training, 2026 sealed.

```text
original Top-10 entries        8,950     the strategy denominator, always
confirmed                      4,705
measurable confirmed           4,656     PRIMARY population (no speed filter)
dense observations           140,929     every 15 s, confirm+15 .. confirm+600
sparse observations            3,041     +900/+1200/+1800/+2400, reported apart
giveback pool / entry          0.898     reproduced to 0.898083
baseline net / entry          -0.0765    reproduced to -0.076530
```

## Two things a reader should not misread

1. **The observation grid runs on the stop-released path** (SPEC D1). That is
   deliberate: letting the 1 ATR stop truncate a forward-opportunity *label* is
   the censored-population defect that understated required stop room 5× in a
   prior study. Economic continuation value is still primary on the **stop-live**
   track and is null once the stop-live terminal has passed, never imputed.

2. **The lifetime-uniform random exit is a benchmark, not a rule.** Its support
   depends on how long the trade actually lived. The length-blind companion is
   the causally implementable one, and the gap between them is the study's
   sharpest single result — see `REPORT.md` §6.
