# Model-B Low-Tail Deterioration Forensic

**Terminal label: `D3 COMPOSITION / PLACEBO EFFECT`** — 2 of 8 D1 conditions pass.
Do not expand ML on this framing.

A tightly scoped forensic extension of
`studies/p80_p90_opportunity_continuation_ml/`. It asks one question: does the LOW
tail of the already-frozen Model-B out-of-sample prediction identify a state where
exiting now is worth materially more than continuing under accepted management?

It does not. See `REPORT.md`.

## What this study did and did not do

```text
DID     re-analyse the frozen 2024 Model-B OOS predictions and forward labels
DID     re-derive first-hit timings the predecessor never persisted (gate V7,
        verified to zero mismatches against the frozen labels)
DID NOT retrain, refit, recalibrate, or construct any estimator (gate V3, static)
DID NOT change features, derive barriers, or optimise a threshold
DID NOT read 2021, 2022, 2023, 2025 or 2026
```

## Population

The brief's 2,991 observations / 781 trades is the **dataset**. The analysis
population is the out-of-sample subset:

```text
1,410 observations / 380 unique trades   (Jul-Dec 2024; Jan-Jun is train-only)
FOLD_1 720/188   FOLD_2 690/192   SHORT 807   LONG 603
```

The predecessor's own headline confirms it: the quoted baseline 48.4397163% is
exactly 683/1410.

## The one substantive amendment

The predecessor priced `EXIT NOW` at the trade's running high-water mark. That is not
a transactable fill. Repriced at the mark:

| | HWM (frozen) | MARK (executable) |
|---|---|---|
| pooled continue − exit | −0.2846 | **−0.1546** |
| bottom decile | −0.7198 | **−0.2764** |
| bottom decile CI | [−1.303, −0.180] excludes 0 | **[−0.845, +0.247] spans 0** |

61.6% of the predecessor's headline effect is fill that cannot be obtained. Both
columns appear in every table; the decision gate reads the mark.

## Layout

```text
SPEC.md      frozen contract, cut grid, gates V1-V8, D1-D4 routing
REPORT.md    the 17 answers and the terminal label
run_study.py staged runner; `--no-timing` skips the Phase-7 re-derivation
implementation/
  common.py    frozen-artifact loading, cuts, economics, trade-clustered bootstrap
  lineage.py   Phase 0 reproduction and the STOP gate
  phases.py    Phases 1-6, 8-10
  timing.py    Phase-7 re-derivation and its self-verification
analysis/gates.py   V1-V8 and the D1/D2/D3/D4 decision
tests/       gate-orientation pins
results/     16 deliverables, listed in SPEC §7
audit/       lint.json, pass_NN.md, status.json, contract_*
```

## Reproduce

```bash
python scripts/causal_lint.py --study studies/model_b_low_tail_deterioration
python -m pytest studies/model_b_low_tail_deterioration/tests/ -q
python -m studies.model_b_low_tail_deterioration.run_study
```

Runs in ~13 s. Stage 0 is a hard STOP: if the predecessor lineage does not reproduce,
no downstream table is written.

## Audit history

`causal_lint` 0 CRITICAL / 0 WARNING. `lookahead-auditor` pass 1 raised one CRITICAL —
the C2/C3/C4 placebo controls selected each trade's *global extreme* observation,
which is hindsight the ML trigger does not get. It was a real defect and it materially
flattered the controls (`C3_DESC` at bottom-25 moved from −1.0992 to −0.1238 once
corrected). The controls are now causal threshold rules; the amendment is recorded in
SPEC §Phase 9, not laundered. The verdict did not change, but the reasoning behind it
did.
