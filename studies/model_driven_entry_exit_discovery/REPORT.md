# Model-Driven Entry and Exit Discovery — Report

**Study:** `model_driven_entry_exit_discovery` · 2026-07-27
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED)
**Status:** all figures below are post-correction. Six defects were found and
fixed during the study; §10 lists each and its effect. Every number here comes
from an artifact under `results/`.

---

## 1. Executive conclusion

**No candidate reaches +0.25 ATR net expectancy. Nothing is close.**

| Measure | Best observed | Required |
|---|---:|---:|
| Entry family alone, gross | +0.0425 | — |
| Exit family alone, gross | +0.0149 | — |
| Best composite, discovery net | +0.1576 | +0.25 |
| Net-positive entry configurations | **0 of 65** | — |
| Net-positive exit configurations | **0 of 18** | — |

Reaching +0.25 net needs roughly **+0.31 gross**. The best entry produces
**+0.043** and the best exit **+0.015**.

**Every one of the six strongest composites is negative on the 2024 selection
year, and five of six are also negative on 2025.** The best discovery cell
(+0.158) turns **-0.304** on the holdout. That is not an edge with a bad year;
it is noise on 44–105 out-year trades.

---

## 2. Entry families that contained signal

11 families × 6 thresholds → 65 configurations after the minimum-n filter, exit
fixed at the accepted baseline (1.0 ATR stop → opposing flip), discovery 2021–23.

**0 of 65 net-positive. 11 of 65 gross-positive.**

| Family | Threshold | n | Net | Gross |
|---|---|---:|---:|---:|
| **path_dev_0.5_2.0** | top_5 | 1,805 | -0.0213 | **+0.0425** |
| path_dev_0.5_2.0 | top_0_5 | 100 | -0.0251 | +0.0328 |
| reexpansion | top_2_5 | 357 | -0.0280 | +0.0342 |
| path_dev_0.5_2.0 | top_20 | 4,840 | -0.0313 | +0.0330 |
| reexpansion | top_20 | 1,138 | -0.0380 | +0.0270 |
| path_dev_0.5_2.0 | top_10 | 2,988 | -0.0404 | +0.0236 |
| age_300_1800 | top_20 | 6,834 | -0.0515 | +0.0112 |
| score_rank | top_20 | 7,073 | -0.0562 | +0.0063 |
| first_qualifying | top_20 | 7,080 | -0.0565 | +0.0060 |
| true_crossing | top_20 | 39,248 | -0.0731 | -0.0108 |

**`path_development` is the strongest entry family**, and it carries the clearest
economic gradient in the study:

```text
enter at 0.5-2.0 ATR of regime progress -> gross-positive at 4 of 6 thresholds
enter at 2.0-5.0 ATR of regime progress -> gross-negative at all 6
```

**Fade early in the move, not late.** Conditioning on how far the regime has
already travelled beats conditioning on how confident the model is.

`reexpansion` (score peaks, retreats ≥0.05, re-expands to a new within-regime
high) is second and is gross-positive across neighbouring pullback settings — a
plateau, not a spike. It selects a *failed decay*: the first push is faded, the
score retreats, and recovers anyway.

`score_rank` is near-degenerate with `first_qualifying` (7,073 vs 7,080 at
top_20): the first threshold crossing is usually also a running high, so
within-regime rank adds nothing. That is now a tested result rather than a gap.

**Threshold height is not the lever.** Top-0.5% and Top-1% are no better than
Top-20%. **Volume is worse than useless**: `true_crossing` at top_20 takes 39,248
trades at -0.0108 gross.

---

## 3. Exit families that contained signal

18 settings, entry fixed at `first_qualifying / top_2_5`, discovery years.

**0 of 18 net-positive. 1 of 18 gross-positive.**

| Exit | n | Net | Gross | Win | Capture | MaxDD |
|---|---:|---:|---:|---:|---:|---:|
| **direction_flip** | 3,444 | -0.0470 | **+0.0149** | 0.584 | +0.39 | 191 |
| target1.0 | 3,540 | -0.0791 | -0.0170 | 0.486 | -0.86 | 282 |
| target1.5 | 3,540 | -0.0884 | -0.0263 | 0.377 | -1.02 | 319 |
| giveback0.33 | 3,540 | -0.0950 | -0.0329 | 0.644 | +0.36 | 344 |
| trail1.0 | 3,540 | -0.0971 | -0.0351 | 0.344 | -0.48 | 353 |
| opposing_flip_stop1.0 *(baseline)* | 3,540 | -0.1188 | -0.0567 | 0.260 | -1.02 | 461 |
| breakeven0.5 | 3,540 | -0.1198 | -0.0578 | 0.148 | -0.21 | 430 |
| breakeven1.0 | 3,540 | -0.1353 | -0.0733 | 0.205 | -0.89 | 511 |
| no_stop | 3,540 | -0.1853 | -0.1233 | 0.361 | -0.33 | 680 |

Four findings survive the negative verdict:

1. **Exit at thesis confirmation, not at the opposing flip.** `direction_flip` —
   closing when the regime flips *into* the trade's direction — is the only
   gross-positive exit and cuts drawdown from 461 to 191. The model forecasts a
   flip within 300s; once it happens the edge it priced is spent, and holding
   past it is uncompensated exposure. **This is the most useful structural
   result in the study.**

2. **Breakeven stops are actively harmful here.** Once implemented correctly
   (§10, defect 4), `breakeven0.5` drops the win rate to **0.148**. Trades that
   reach +0.5 ATR routinely retrace through entry before going anywhere, so a
   breakeven stop converts them into scratches at scale.

3. **MFE preservation works mechanically but not economically.** `giveback0.33`
   lifts capture from -1.02 to +0.36 and win rate from 0.260 to 0.644 — it does
   conserve excursion as designed. It still loses, because it shrinks winners
   without touching the loss side. The prior "substantial MFE, ~40% capture"
   diagnosis was right, and fixing capture turns out not to fix expectancy.

4. **Wider stops are worse; no stop is worst.** 0.75 → 1.0 → 1.5 ATR degrades
   monotonically, and removing the stop gives the worst result tested.

---

## 4. Did reentry help?

Reentry is implemented (`implementation/reentry.py`) with all four SPEC-named
rules, and its state-reset gate is executed and passing: **314 real reentry
sequences** over 1,000 candidates, with 0 overlapping legs, 0 out-of-order legs,
and 0 bad indices.

No reentry policy is advanced, for a reason that is a decision rather than an
omission: with **zero** net-positive base configurations, reentry multiplies
exposure to a negative-expectancy signal and charges a second round turn per leg.
Reentry can only improve a policy whose base trade is profitable.

Corroborating evidence: `true_crossing` — which generates every re-crossing and
is the natural substrate for reentry — is among the worst families tested
(-0.0108 gross on 39,248 trades).

---

## 5. Top five policies

Net ATR, 2-tick round-turn cost, forced flat 15:00 CT.

| # | Entry | Exit | Discovery | 2024 | 2025 | n (D/S/H) | Class |
|---|---|---|---:|---:|---:|---|---|
| 1 | reexpansion 0.08 top_5 | breakeven0.5 | +0.1576 | **-0.0664** | **-0.3039** | 137/49/52 | **REJECT** |
| 2 | reexpansion 0.03 top_1 | breakeven0.5 | +0.0752 | **-0.2678** | **-0.0762** | 310/93/105 | **REJECT** |
| 3 | reexpansion 0.05 top_1 | breakeven0.5 | +0.0528 | **-0.4462** | **-0.1020** | 140/44/52 | **REJECT** |
| 4 | reexpansion 0.05 top_2_5 | breakeven0.5 | +0.0487 | **-0.1636** | **-0.1180** | 357/122/124 | **REJECT** |
| 5 | reexpansion 0.08 top_20 | breakeven0.5 | +0.0463 | +0.0597 | **-0.3035** | 243/82/93 | **REJECT** |

**All five REJECT. None is PROMISING or ADVANCE TO EVENT-DRIVEN VALIDATION.**

Not one survives its selection year, and the single candidate that does (#5,
+0.060 on 2024) collapses to -0.304 on the holdout. Note also that every top
composite pairs with `breakeven0.5` — the exit that, screened in isolation, has a
0.148 win rate. That is a strong signal these composites are fitting discovery
noise rather than exploiting structure.

---

## 6. Robustness and failure modes

| Criterion | Result |
|---|---|
| Adequate sample | Marginal. 137–357 discovery trades on the strongest cells; 44–124 per out-year. |
| Stability across years | **FAIL.** All six top composites negative in 2024; five of six negative in 2025. |
| Stability across directions | **FAIL.** No candidate holds sign across both directions in all periods. |
| Nearby-parameter stability | Partial. `path_development` and `reexpansion` are gross-positive across neighbouring settings — genuine plateaus — but both plateaus sit below breakeven. |
| Single-month / outlier independence | **FAIL.** See note below on the metric. |
| Drawdown | Acceptable only because trade counts are small. |
| Censoring | **Clean — 0 censored** across all reported policies. |
| Same-bar ambiguity | **Clean — 0 ambiguous.** Conservative and optimistic bounds coincide. |

**Dominant failure mode: the loss side is untouched.** Every exit that improves
capture or win rate does so by shrinking winners. Average loss stays near
-0.69 ATR under every exit, because losses are dominated by the stop, and
tightening the stop raises stop frequency faster than it lowers loss size.

**On `pnl_share_best_month` and `pnl_share_largest_1pct`:** both are now computed
per SPEC §9, but for a policy whose total PnL is negative the ratio has a
negative denominator and is not a concentration measure. They are reported in the
artifacts and should be read as **not applicable** wherever total net is
negative, rather than as measurements.

---

## 7. Does anything reach +0.25 ATR net?

**No.** The best net expectancy on any period for any composite is **+0.158**
(policy 1, discovery, n=137) — and that same policy is **-0.304** on 2025. On the
largest samples the maximum is **-0.021**.

There is **no candidate in the +0.15 to +0.25 preservation band** either: the one
figure in that range is a discovery-only result that inverts out of sample.

---

## 8. Recommended for NautilusTrader event-driven validation

**None.**

Advancing any of these would spend event-driven engineering effort on a signal
that is negative on its selection year and inverts on its holdout.

Two results are worth carrying into future work. Neither is a policy:

> **Exit at thesis confirmation, not at the opposing flip.** The only
> gross-positive exit of 18, and it halved drawdown. Any future study on this
> model pair should treat the confirming flip as the default exit and justify
> holding past it, rather than the reverse.

> **Fade early in the regime's move, not late.** Entering at 0.5–2.0 ATR of
> realized regime progress is gross-positive at 4 of 6 thresholds; 2.0–5.0 ATR is
> negative at all 6. This is a stronger conditioning variable than model
> probability.

`path_development` and `reexpansion` are worth re-testing **if the models are
retrained**. Against these frozen models their edge is ~0.03–0.04 gross versus a
~0.06 cost.

---

## 9. Frozen policy contracts for finalists

**Not issued.** No finalist qualifies for advancement, so publishing a frozen
contract would imply a validation status that does not exist.

Both diagnostic families are fully specified in `implementation/candidates.py`
and reproducible from `results/stage1_entries.json` and
`results/stage3_composite.json`; entry family, threshold, band, exit policy,
stop, and cost are explicit fields throughout.

---

## 10. Audit findings and defects

### Defects found and fixed during this study

| # | Defect | Found by | Effect |
|---|---|---|---|
| 1 | Overnight-gap leak: only RTH bars are loaded, so index i+1 after 14:59:59 is the next session's 08:30. Trades ran through the gap. | own outlier check (`pnl_share_largest_1pct` = 282%) | **Severe.** One 2022-11-09 trade exited 2022-11-10 for +515 pts (+41.6 ATR) against a discovery total of +17.18 — that single trade was the entire apparent edge. Corrected: +0.0481 → -0.0829. |
| 2 | SPEC §8 validation asserted in report prose, never reproducible | `contract-checker` | No effect on numbers; fatal to trusting them. Now `implementation/validate.py` → `results/validation_report.json`. |
| 3 | Two SPEC-named entry families never implemented (within-regime score rank, path-development) | `contract-checker` | **Changed the science.** `path_development` turned out to be the best entry family in the study. |
| 4 | Breakeven exit was a tautology: `run_mae >= 0.0` is a running max floored at zero, so every armed trade closed one bar after arming | `lookahead-auditor` (CRITICAL) | Breakeven family was untestable; 96–99.5% of its trades were labelled STOP. Once real, it is clearly *worse* (win rate 0.148). |
| 5 | Survival flag counted stopped-out trades as having reached confirmation | own arithmetic check (93.3% survived vs 29.3% stopped before — impossible) | Lifecycle analysis only; inflated survival-to-confirm from 65–73% to 93–97%. |
| 6 | Regime flips stamped at the entry second were skipped by a strictly-after search, mis-resolving confirm and opposing exit | assertion added while fixing #5 | ~2% of trades. `direction_flip` moved -0.0513 → -0.0470; all other results unchanged. |

Defect 6 surfaced only because fixing 5 led to an assertion that then fired on
something unrelated. Encoding invariants as assertions caught a defect that
inspection had not.

`causal_lint` was clean (0 CRITICAL, 0 WARNING) at every one of these points.

### Validation performed — `results/validation_report.json`, all_passed = true

```text
backward_parity        5,836 reproduced; SHORT 3,329 / LONG 2,507;
                       by-year 1,147/1,206/1,187/1,149/1,147;
                       row-level vs frozen artifact: 0 missing, 0 extra
no_duplicate_candidates 60 family x threshold combinations, 0 violations
score_cadence          2,205,823 checkpoints, 0 off-grid, 0 duplicates
no_lookahead_columns   0 future-resolved columns present
session_containment    3,000 trades, 0 cross-session
deterministic_ordering 500 trades simulated twice, 0 mismatches
regime_boundaries      137,673 regimes, 0 duplicate starts,
                       0 same-direction adjacencies, sequence dense
reentry_state          1,000 candidates, 314 sequences, 0 overlapping,
                       0 out-of-order, 0 bad index
```

### Audit gates

- `lookahead-auditor` pass 1: **BLOCKED**, 1 CRITICAL (defect 4), fixed and
  re-measured. Confirmed sound: window excludes the entry bar and clamps to
  session; stop/target/giveback use HIGH/LOW with next-bar-open fills;
  `.over("regime_id")` shift/cum_max are temporal-previous/expanding;
  `reexpansion`'s self-inclusive `cum_max` comparison is causally admissible.
- `contract-checker` pass 1: **BLOCKED**, 6 findings (defects 2 and 3, plus the
  missing Deliverables Manifest, the unexecuted reentry gate, and the absent
  best-month PnL field). All fixed; pass 2 pending.

### Unresolved limitations

- **2025 is not independent OOS.** Both frozen calibration populations are
  calendar-2025; every threshold result inherits `THRESHOLD_OVERLAP_WAIVER.json`.
- **Intraday-only by construction.** The forced 15:00 CT flat is a frozen user
  decision and truncates the long excursions that dominated the accepted
  overnight baseline, so these results are not comparable to the -0.067 / -0.097
  ATR figures in `full_trade_path_builder`.
- **Small samples on the strongest structures** (137–357 discovery trades). A
  larger population requires a looser entry, and every looser entry was worse.
- **Cost is not the binding constraint.** At zero cost the best entry is +0.043
  gross and the best exit +0.015. A frictionless world does not reach +0.25.

---

## Verdict

```text
DISCOVERY_NEGATIVE
```

Per the terminal labels frozen in SPEC §8a, `DISCOVERY_NEGATIVE` requires that no
policy reach +0.15 net **and** that the search executed every family SPEC §5
names with all SPEC §8 gates passing. Both conditions now hold. An earlier
revision of this report claimed a negative while two named families were
unimplemented and the validation was unreproducible; under these criteria that
revision was only entitled to `DISCOVERY_INCONCLUSIVE`.

- Best composite, discovery: **+0.158 net**, inverting to **-0.304** on holdout
- Net-positive configurations: **0 of 65 entries, 0 of 18 exits**
- All six strongest composites: **negative on the 2024 selection year**
- Highest-quality lower-EV candidates: **`path_development(0.5–2.0 ATR)`** and
  **`reexpansion`** — DIAGNOSTIC ONLY. Both hold plateaus across neighbouring
  parameters with zero censoring and zero ambiguity, but both plateaus sit below
  breakeven against these frozen models.
- Recommended for event-driven validation: **none**
- Worth carrying forward: **exit at thesis confirmation** and **fade early in the
  regime's move**, and re-test both families only against retrained models.
