# top10_fast_confirm_runner_path

**Verdict: C — CONFIRMATION SPEED IS NOT ECONOMICALLY INFORMATIVE, BUT POST-CONFIRM PATH IS**

Does an immediate Top-10 fade entry whose confirming flip arrives within **120
seconds** (and before the 1.00 ATR stop) have a materially different, more
exploitable post-confirmation path?

**Short answer.** Fast confirmation identifies a *worse* population, not a better
one — monotonically, in all five years. The post-confirmation path *does* carry
real causal separation between eventual ≥3 ATR runners and <2 ATR failures
(AUC 0.756 at +120 s, containment-controlled, 5/5 years). It cannot be turned
into an exit rule: the 1.00 ATR stop already acts on 40% of the trades the signal
flags, and every policy loses to a count-matched random placebo.

See `REPORT.md` for the full result and `SPEC.md` for the frozen contract.

---

## Headline numbers

```text
original Top-10 entries              8,950
confirmed                            4,705   (4,656 measurable, 49 reconciled)
FAST_CONFIRM_120                     2,383   51.2% of confirmed, 26.6% of entries

fast  mean net 0.670 ATR   P(>=3 ATR) 0.346   median MAE to confirm 0.181
slow  mean net 0.990 ATR   P(>=3 ATR) 0.404   median MAE to confirm 0.560

best causal separator   ret_from_entry @ +120s   AUC 0.756   5/5 years
best policy             P2_PROG60_LE0   +0.0029 ATR/entry   loses to placebo
```

---

## Layout

```text
SPEC.md          frozen contract; §1 records the three owner decisions and
                 §8 the dated separation-gate amendment
REPORT.md        the result, the 14 brief questions, defects, limitations
implementation/
  engine.py      per-trade window, two terminals (stop-live + unconstrained),
                 10 causal landmark states, armed giveback + stall geometry
  build.py       trade panel, landmark-state panel, Phase-10 score context
  validate.py    the 15 SPEC §9 gates -> results/validation_report.json
analysis/
  phases.py      Phases 0-11 aggregation -> the deliverable tables
  policies.py    Phase 12 (conditional): 4 policies, runner destruction,
                 count-matched random placebo
  close_out.py   writes the 14 report answers + the final label into
                 summary.json, EXECUTING the SPEC §6 decision table rather
                 than asserting its outcome
tests/           16 deterministic tests on synthetic bars
audit/           causal_lint + lookahead-auditor + contract-checker verdicts
results/         parquet + CSV mirrors, validation_report.json, summary.json
```

## Reproduce

```bash
python -m studies.top10_fast_confirm_runner_path.implementation.build
python -m studies.top10_fast_confirm_runner_path.analysis.phases
python -m studies.top10_fast_confirm_runner_path.analysis.policies   # conditional
python -m studies.top10_fast_confirm_runner_path.analysis.close_out  # 14 answers + label
python -m studies.top10_fast_confirm_runner_path.implementation.validate
python -m pytest studies/top10_fast_confirm_runner_path/tests -q
```

Substrate: `data/canonical/regime_complete_v1/` and the frozen arm table
`studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`.
No recollection. 2021–2025 RTH only; **2026 untouched**.

---

## Three things worth carrying forward

1. **Giveback is the wrong axis.** At +120 s a >0.50 ATR drawdown in the
   high-progress cell still returns +1.616 ATR with P(≥3 ATR) = 0.573. Forward
   progress moves the outcome from 0.157 to 0.612; drawdown barely moves it.
   Every giveback-based rule in this program has been aiming at the wrong
   variable.

2. **Two event definitions in this family are degenerate and must be armed.**
   `running max − low ≥ level` fires on 100% of trades (a trade merely below
   entry books a "giveback" it never earned); a stall clock started at
   confirmation fires on 100% (a trade that never went favorable is credited with
   a stall). Both need an arming condition before they carry any information.

3. **A path variable that mechanically bounds its own label is not a predictor.**
   `eventual MaxMFE ≥ run_mfe` by construction, so trades already at ≥2.0 ATR
   running MFE are guaranteed ≥3-or-excluded positives — 17.7% of the labelled
   set at +120 s, 100% of them positive. Dropping them costs 0.05–0.09 AUC. Any
   future study scoring a running extremum against an eventual extremum needs
   this control.
