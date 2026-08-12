# Post-Confirmation Retracement & Recovery — REPORT

**Terminal label: `R4_NO_USEFUL_FAILED_RECOVERY_STATE`**

**Population:** 4,656 measurable confirmed trades · 4,705 confirmed · 8,950 original
Top-10 entries · 2021–2025 · 2026 sealed and never read
**Lineage:** REPRODUCED, 0 of 40 checks failed
**Gates:** 14/14 · **Tests:** 15 · **causal_lint:** 0/0 · **lookahead-auditor pass 2:** PASS (0 critical)

---

## Summary

Retracement after a rung is not a state. It is what happens to **93–99%** of
trades that reach one. Of those that retrace, **75–79%** go on to reclaim the
entire high-water mark, and they do it in a **median 55 seconds**. There is no
population left over to exit.

The study asked whether "reached X ATR, retraced D ATR, failed to recover Y%
within T seconds" identifies terminal deterioration. Across 96 frozen rules the
best continuation-minus-exit value is **−0.098 ATR** and the median is
**−0.015 ATR**. Exactly **1 of 96** confidence intervals excludes zero, against
**~4.8 expected by chance** at 95%. The result is not merely weak; it is below
the chance rate.

The decisive comparison is `RETRACEMENT_ONLY`, which exits at the arm bar with no
recovery condition attached. The full rule beats it by **0.0023 ATR** — under a
tenth of one tick. Whatever small edge exists belongs to the retracement, and the
recovery condition is decoration on top of it.

**This is an R4 and it is not to be softened.**

---

## 1. Lineage — reproduced exactly, nothing repaired

| Quantity | Observed | Accepted | Status |
|---|---|---|---|
| Original Top-10 entries | 8,950 | 8,950 | exact |
| Confirmed | 4,705 | 4,705 | exact |
| Stopped before confirm (by subtraction) | 4,245 | 4,245 | exact |
| Stopped before confirm (by terminal label) | 4,245 | 4,245 | exact |
| Measurable confirmed | 4,656 | 4,656 | exact |
| Non-measurable | 49 | 49 | exact |
| Giveback pool / entry | 0.8980826 | 0.89808 | Δ 2.6e−06 |
| Baseline net / entry | −0.0765296 | −0.07653 | Δ 3.6e−07 |
| Per-rung membership, all 6 rungs | — | — | exact |
| Rung timestamp mismatches | 0 | 0 | exact |

Phase 0 initially failed, reporting 4,705 entries against an accepted 8,950 and
**zero** stopped-before-confirm trades against an accepted 4,245. The cause was
in the check, not the population: it read `confirmed_population()`, which filters
to confirmed labels by construction and therefore cannot express either quantity.
Three definitions were restored from the accepted predecessor
(`post_confirm_profit_ratchet/implementation/validate.py:167-177`):

- **entries** is the 8,950-row ARMED panel.
- **pool** sums giveback over `nat_kind == "OPPOSING_FLIP"` terminals only.
- **baseline** is the confirmed cohort's net **plus** the 4,245 trades stopped
  before they ever confirmed.

That last one carries the important warning, in the predecessor's own words:
*omitting that cohort is not a smaller baseline, it is a different strategy.*
Left uncorrected it would have shown a **+0.430 ATR/entry** baseline instead of
**−0.077** — a profitable-looking strategy manufactured purely by deleting the
losers the entry rule pays for before any exit rule can act.

Both counts are now derived two independent ways (subtraction across two panels,
and terminal label) so that a shared error cannot reconcile.

---

## 2. Q1 — How often do confirmed trades retrace? Near-universally.

| Rung | D=0.50 | D=0.75 | D=1.00 | D=1.25 |
|---:|---:|---:|---:|---:|
| 1.0 | 93.1% | 98.2% | 99.4% | 98.9% |
| 1.5 | 94.2% | 97.9% | 99.1% | 98.8% |
| 2.0 | 95.8% | 98.2% | 98.8% | 98.5% |

Median time from rung to arm is 20–23s at D=0.50 and 163–167s at D=1.25.

A condition that fires on 99% of the population carries almost no information.
This alone caps how useful any rule built on it can be, and it frames everything
below.

## 3. Q2/Q3 — Recovery is the norm, and it is fast

At rung 1.0, D=0.50, over 3,871 fresh arms:

| Level | P(recover before terminal) | P(≤60s) | Median secs | p90 secs |
|---|---:|---:|---:|---:|
| R25 | 0.925 | 0.829 | 5 | 62 |
| R50 | 0.858 | 0.674 | 17 | 144 |
| R75 | 0.797 | 0.512 | 35 | 219 |
| R100 (full HWM) | 0.752 | 0.401 | 55 | 267 |
| NEW_HWM | 0.743 | 0.377 | 59 | 278 |

Deeper rungs recover slightly *more* often (R100 rises to 0.792 at rung 2.0), not
less. Three trades in four fully reclaim the high-water mark.

## 4. Q4 — Recoverers pay little to get back

Median additional adverse excursion before recovery is well under 0.5 ATR; p90 is
~1.10 ATR and p95 ~1.44 ATR for a full reclaim. Arms that never recover fall a
median **1.60 ATR** further.

So the two populations *do* end differently. The question the rest of the study
answers is whether you can tell them apart **at the moment you would have to
act** — and the answer is no.

## 5. Q5/Q6 — Failure does not become progressively informative

Of 125 (state × level × rung × D) cells with at least three horizons, only **5**
worsen monotonically across all of them. For four-point sequences chance alone
gives ~4%. The five survivors do not form a neighbourhood: two share rung 4.0 but
sit at D=0.75 and D=1.25, skipping the D=1.00 cell between them.

The R1 clause requires ordered deterioration **and** ≥2 neighbouring cells
agreeing. The ordering exists at chance frequency and the neighbourhood does not
exist at all.

Best rule of 96: **−0.098 ATR**, CI [−0.201, −0.006]. Median: **−0.015 ATR**.
**1 of 96** CIs excludes zero versus ~4.8 expected by chance.

## 6. Q7/Q8 — The controls match it

| Control | Mean rule − control (ATR) | Cells where control wins |
|---|---:|---:|
| `RETRACEMENT_ONLY` | **−0.0023** | 45.8% |
| `CURRENT_RETURN_ONLY` | −0.0078 | 37.5% |
| `TIME_SINCE_CONFIRM_ONLY` | −0.0054 | 30.2% |
| `DRAWDOWN_FROM_HWM_ONLY` | −0.0187 | 29.2% |
| `TIME_SINCE_RUNG_ONLY` | −0.0137 | 20.8% |

Every gap is a fraction of a tick (0.25 pt against a ~9.6 pt RTH ATR ≈ 0.026 ATR).
`RETRACEMENT_ONLY` is the one the SPEC named decisive: if it matches the rule, the
recovery condition is decoration and the answer is R4. It matches to 0.0023 ATR
and wins outright in nearly half of all cells.

> `RANDOM_TIMING` is reported in `placebo_controls.csv` but is **not** used to
> decide the label. Its population conditions only on `retracement_d` — the arm
> panel carries no horizon dimension — so it is not like-for-like at a given
> (horizon, level). Recorded as note N2 by `lookahead-auditor` pass 2, disclosed
> rather than silently dropped.

## 7. Q9 — Runner destruction is near-symmetric

Median across all states and horizons: **13.3%** of ≥3 ATR runners and **21.2%**
of ≥4 ATR runners intercepted, at a median loser:winner ratio of **1.38**
(range 1.06–2.05). At the aggressive end, the 30s states intercept **87–89% of
winners** against 94% of losers — a ratio of 1.06.

You cannot cut the losers without cutting the winners at nearly the same rate.

## 8. Q10/Q11 — No stability by side, by year, or across cells

- **Side:** 40 of 48 side-split cells (**83.3%**) invert sign between LONG and
  SHORT. LONG frequently favours *continuing* exactly where SHORT favours exiting.
- **Year:** **no** cell is consistent across all five years; the best is 4 of 5,
  reached by 10 of 120 cells.
- **Cells:** no broad knee. The handful of coherent-looking cells are isolated.

## 9. Q12 — Which of R1–R4?

The label is computed from the frozen conditions in `run_study.py::_terminal_label`
and written to `results/summary.json`, not asserted in prose. **1 of 7 clauses
passes:**

| Clause | Result | Deciding number |
|---|---|---|
| Recovery condition adds value | ✗ | 0.0023 ATR vs 0.05 material threshold |
| Ordered deterioration | ✓ | 5 monotone cells (of 125) |
| Beats decisive controls | ✗ | controls win 32.7% of cells |
| Sign stable across sides | ✗ | 83.3% inverted |
| Runners preserved | ✗ | loser:winner 1.38 |
| More significant than chance | ✗ | 1 CI excludes zero vs 4.8 expected |
| Year consistent | ✗ | 0 cells consistent across 5 years |

The single passing clause clears a deliberately generous bar (≥2 monotone cells)
and 5 of 125 is the chance rate, so it should not be read as support.

**Thresholds, disclosed** (SPEC Amendment A2): material effect 0.05 ATR
(≈2 ticks); decisive-control win rate <0.25; monotone cells ≥2; side inversion
<0.5; loser:winner ≥2.0. Each is set to favour the hypothesis. The observed
values miss by wide margins — 0.0023 against 0.05, and 0.833 against 0.5 — so
the label does not turn on where these are placed. `results/summary.json` emits
every clause with its deciding number, so the label can be recomputed under
different thresholds without re-running the study.

**`R4_NO_USEFUL_FAILED_RECOVERY_STATE`.**

## 10. Q13 — Next step: abandon this axis

**Do not train an ML recovery/failure model.** SPEC §8.2 makes ML conditional on
the descriptive result first establishing a real state. It did not. There is no
state here for a model to sharpen — the geometry fires on 99% of trades, resolves
favourably 75% of the time, and its economic signature is indistinguishable from
"the trade is currently down a bit."

**Do not build a price-only exit architecture on this state either.** That is the
R2 branch and it requires the deterioration to be real but simply capturable;
here the deterioration is not real at actionable horizons.

**More years will not rescue it.** That is the R3 branch, for coherent geometry
starved of data. These cells are not starved — the largest carry 1,285–2,077
triggering trades. The intervals are wide because the effect is absent, not
because the sample is small.

### What this closes

This is the fourth independent attempt to predict terminal deterioration from
local post-confirmation price behaviour, and the fourth null:

- Post-confirm exit **timing** — state predicts scale, not sign
- Post-confirm exit **protection** (profit ratchet) — successes draw down *more*
  than failures
- **Giveback/stall** rules — cut 70% of ≥3 ATR runners
- **Retracement/recovery** geometry — this study

The consistent shape across all four is that drawdown inside a live fade trade is
**not** a deterioration signal; it is what winning trades do on their way to
winning. The 1 ATR stop already collects what edge exists in this direction.

### What remains open

Nothing in this study speaks to **sizing**, which is where the predecessor line
pointed and where no null has yet been recorded. Post-confirmation state predicts
the *scale* of the outcome without predicting its *sign* — a property that is
useless for timing an exit and potentially useful for choosing a position size.
That is a different question on a different axis and is not opened here.

---

## 11. Defects found and fixed during this study

Recorded because three of the four were invisible to a passing gate suite.

| Defect | How it presented | Caught by |
|---|---|---|
| Phase 0 read `confirmed_population()` (confirmed-only) as the original-entry population | 4,705 entries vs 8,950; **zero** stopped-before-confirm vs 4,245; baseline **+0.430** instead of −0.077 ATR/entry | the Phase 0 hard gate itself, on first successful execution |
| `ARM_CLOSED_AT_HWM` arms not excluded from recovery primaries | recovery target below the arm bar's own close ⇒ recovery satisfied at t=0 by construction, inflating `p_recover_*` | `lookahead-auditor` pass 1 |
| Gate V3's HWM scanner matched bare text | flagged its own comment and its own regex literal; failed on a package with zero real leaks | first execution of the `validate` stage |
| Gate V8 covered only the seven derived CSVs | `recovery_state_panel.parquet` shipped with **no `path` column at all** while the suite reported 14/14 | `contract-checker` pass 1 |

The last one is the instructive one: a gate that does not cover the deliverable
cannot vouch for it, and a green suite says nothing about what it never opened.
V3 and V8 are now each pinned in both directions by tests that assert the gate
still *fails* on the defect it exists to catch (`test_v3_hwm_scan.py`,
`test_v8_path_labelling.py`).

---

## Reproduce

```bash
python -m studies.post_confirm_retracement_recovery.run_study --stage all
python -m pytest studies/post_confirm_retracement_recovery/tests/ -q
python scripts/causal_lint.py --study studies/post_confirm_retracement_recovery
```

Runtime ~1m45s. Deliverables 1–20 of SPEC §8 are present under `results/`,
`audit/`, and this file.
