# P90 Conditional Losing-5s-Flip Failure Exit

The predecessor showed that exiting on **every** adverse 5s flip is too
aggressive. This study asks the narrower question: tolerate 5s counter-regimes
while the trade is at or above entry, and treat a counter-regime **below entry**
as evidence the P90 attempt is failing.

```text
adverse 5s flip + current_return_atr <  0  ->  EXIT
adverse 5s flip + current_return_atr >= 0  ->  IGNORE, keep going
```

**Verdict: `G4_NO_USEFUL_EDGE`.** 27/27 gates. See `REPORT.md`.

## Status

| Phase | State |
|---|---|
| 0 — predecessor + accepted FULL-lifecycle reconciliation | **PASS** — parity exact on all 8,950 arms |
| 1–11 — flips, coverage, confusion, economics, placebo | **complete** |
| gates V1–V13 | **27/27 pass** |
| `causal_lint` | **PASS** — 0 CRITICAL, 0 WARNING |
| `lookahead-auditor` / `contract-checker` | see `audit/status.json` |

## Headline

The signal is **real and it does not pay**. Losing adverse flips are strongly
associated with failure — but the money saved on failures is almost exactly the
money lost on good trades.

| | ATR |
|---|---:|
| failure ATR saved | **+2,158.30** |
| good-trade ATR forfeited | **−2,119.58** |
| net difference | **+38.72** |
| **savings / sacrifice ratio** | **1.018** |
| net per ORIGINAL arm | **+0.0043**, CI **[−0.0222, +0.0295]** |

Per original P90 arm, net ATR after the accepted 2-tick round turn:

| policy | exp/arm | MaxDD | median hold |
|---|---:|---:|---:|
| `BASELINE_1.00` | −0.0805 | 801.0 | 329s |
| `COND_1.00` | −0.0762 | 752.1 | 56s |
| **`BASELINE_0.75`** | **−0.0677** | **694.1** | 204s |
| `COND_0.75` | −0.0762 | 754.8 | 55s |
| `PLACEBO_COND_1.00` | −0.0808 | 795.9 | 153s |

**`BASELINE_0.75` — just tightening the stop, with no conditional rule at all —
is the best policy in the study.**

## Run it

```bash
python -m studies.p90_conditional_losing_5s_exit.implementation.lineage
python -m studies.p90_conditional_losing_5s_exit.run_study
```

Phase 0 takes ~20s (it re-walks all 8,950 arms for the parity gate); the study
~25s. Both depend on the predecessor's 5s flip timeline in
`studies/p90_5s_regime_impulse/_work/`; rebuild it with
`python -m studies.p90_5s_regime_impulse.implementation.regime_5s` if absent.

## Inherited vs new

**Inherited verbatim** — P90/Top-10 arm population, the 5s regime engine and
flip timeline (imported from the predecessor, not reimplemented), entry
qualification, entry-fill convention, ATR, cost, session handling.

**New here** — the conditional rule, and a parameterised re-expression of the
accepted FULL lifecycle (`walks.py::continuation_label`) that accepts a second
stop distance. Gate V2 proves that re-expression reproduces the accepted
function's label and all four metrics **exactly on every one of the 8,950 arms**.

## The baseline is the FULL lifecycle

Two accepted lifecycles exist in the frozen artifact. This study uses **FULL**
(hold through confirmation, exit at the opposing flip), not the predecessor's
walk-A (exit at confirmation) — it is what the brief describes, and it is the
only one under which Phase 8's `AFTER_CONFIRM` is reachable rather than a
declared-empty category. Walk A is still reproduced in Phase 0 and still defines
the confusion-matrix TARGET. See `SPEC.md` §2.

## Layout

```text
SPEC.md            the frozen contract, incl. the 8.2 verdict-logic amendment
REPORT.md          the 16 answers, and why the verdict is G4
implementation/
  policy.py        FULL-lifecycle baseline, the conditional rule, the placebo
  lineage.py       Phase 0 -- reconcile or ABORT
  analysis.py      Phases 1-11 tables
  validate.py      gates V1-V13 and the computed verdict
results/           SPEC section 8 deliverables (CSV/parquet not committed)
```
