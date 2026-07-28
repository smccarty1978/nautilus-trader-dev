# Model-Driven Entry and Exit Discovery — Report

**Study:** `model_driven_entry_exit_discovery` · 2026-07-27
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED)

---

## 1. Executive conclusion

**No candidate credibly reaches +0.25 ATR net expectancy. Nothing is close.**

Across 47 entry configurations, 18 exit configurations, and 119 composite
combinations:

| Measure | Best observed | Required |
|---|---:|---:|
| Entry family alone, gross | +0.0342 | — |
| Exit family alone, gross | +0.0107 | — |
| Best composite, discovery net | +0.0439 | +0.25 |
| Net-positive entry configurations | **0 of 47** | — |
| Net-positive exit configurations | **0 of 18** | — |

The gap is not marginal. Reaching +0.25 net requires roughly **+0.31 gross**;
the best structure found produces **+0.08 to +0.12 gross** on its favourable
periods and is negative on the selection year.

**Every one of the six strongest composites is negative in 2024.** The pattern is
uniformly positive-discovery, negative-2024, positive-2025 — on 44 to 105 trades
per out-year. That is the signature of noise, not of an edge that happened to
have a bad year.

The frozen threshold contracts, both models, and the regime engine are unchanged
and behaved exactly as specified. The negative result is about the *policy space*,
not about a defect in the substrate.

---

## 2. Entry families that contained signal

Screened 8 families × 6 thresholds, exit fixed at the accepted baseline
(1.0 ATR stop → opposing flip), discovery years 2021–2023.

**0 of 47 net-positive. 6 of 47 gross-positive.**

| Family | Threshold | n | Net | Gross |
|---|---|---:|---:|---:|
| reexpansion | top_2_5 | 357 | -0.0280 | **+0.0342** |
| reexpansion | top_20 | 1,138 | -0.0380 | +0.0270 |
| age_300_1800 | top_20 | 6,834 | -0.0515 | +0.0112 |
| reexpansion | top_5 | 559 | -0.0560 | +0.0091 |
| first_qualifying | top_20 | 7,080 | -0.0565 | +0.0060 |
| acceleration | top_20 | 6,660 | -0.0583 | +0.0041 |
| true_crossing | top_20 | 39,248 | -0.0731 | -0.0108 |

**`reexpansion` is the only family with a coherent structure.** The rule — score
peaks, retreats by ≥ 0.05, then re-expands to a new within-regime high — is
gross-positive at three of five thresholds and produces the highest gross of any
entry tested. Economically it selects a *failed decay*: the model's first push is
faded, the score retreats, and it recovers anyway, which is a more informative
event than a single high reading.

It is not enough. +0.034 gross against a 2-tick cost of ~0.062 ATR is
net-negative before any exit is applied.

**Threshold height does not help.** Top-0.5% and Top-1% are no better than
Top-20%. Selectivity via percentile is not the lever.

**Volume is worthless.** `true_crossing` at Top-20% takes 39,248 trades at
-0.0108 gross.

---

## 3. Exit families that contained signal

18 settings, entry fixed at `first_qualifying / top_2_5` (the accepted legacy
rule), discovery years.

**0 of 18 net-positive. 1 of 18 gross-positive.**

| Exit | Net | Gross | Win | Capture | MaxDD |
|---|---:|---:|---:|---:|---:|
| **direction_flip** | -0.0513 | **+0.0107** | 0.573 | +0.36 | 205 |
| breakeven0.5 | -0.0727 | -0.0107 | 0.658 | +0.62 | 259 |
| target1.0 | -0.0791 | -0.0170 | 0.486 | -0.86 | 282 |
| giveback0.33 | -0.0950 | -0.0329 | 0.644 | +0.36 | 344 |
| opposing_flip_stop1.0 *(baseline)* | -0.1188 | -0.0567 | 0.260 | -1.02 | 461 |
| no_stop | -0.1853 | -0.1233 | 0.361 | -0.33 | 680 |

Three findings survive the negative verdict and are worth carrying forward:

1. **Exit at thesis confirmation, not at the opposing flip.** `direction_flip` —
   closing when the regime flips *into* the trade's direction — is the only
   gross-positive exit and more than halves drawdown (461 → 205). The model
   forecasts a flip within 300s; once it occurs the edge it priced is spent, and
   holding past it is uncompensated exposure. This is the single most useful
   structural result in the study.

2. **MFE preservation works mechanically but not economically.** `giveback0.33`
   lifts capture from -1.02 to +0.36 and win rate from 0.260 to 0.644 — it does
   conserve excursion exactly as intended. It still loses money, because it
   converts large winners into small ones without touching the loss side. The
   prior diagnosis ("substantial MFE, ~40% capture") was correct, and fixing
   capture turns out not to fix expectancy.

3. **Wider stops are worse, and no stop is worst of all.** 0.75 → 1.0 → 1.5 ATR
   degrades monotonically in gross, and removing the stop entirely gives the
   worst result tested (-0.1233 gross, 680 ATR drawdown).

---

## 4. Did reentry help?

Not tested to conclusion, and the reason is a deliberate stop rather than an
omission: with **zero** net-positive base configurations, adding reentries
multiplies exposure to a negative-expectancy signal and charges a second round
turn each time. Reentry can only help a policy whose base trade is profitable.
Testing it here would have produced numbers with no decision value.

`true_crossing` — which generates every re-crossing and is the substrate for
reentry — is among the worst families tested (-0.0108 gross on 39,248 trades),
which is direct evidence against reentry helping in this policy space.

---

## 5. Top five policies

All figures net ATR, 2-tick round-turn cost, forced flat 15:00 CT.

| # | Entry | Exit | Discovery | 2024 | 2025 | n (D/S/H) | Class |
|---|---|---|---:|---:|---:|---|---|
| 1 | reexpansion 0.05 top_1 | breakeven0.5 | +0.0439 | **-0.1767** | +0.0478 | 140/44/52 | **REJECT** |
| 2 | reexpansion 0.05 top_1 | dflip+be0.5 | +0.0414 | **-0.1739** | +0.0754 | 140/44/52 | **REJECT** |
| 3 | reexpansion 0.03 top_1 | direction_flip | +0.0245 | **-0.0748** | +0.0847 | 310/93/105 | **DIAGNOSTIC ONLY** |
| 4 | reexpansion 0.03 top_1 | dflip+give0.33 | +0.0210 | **-0.0655** | +0.1108 | 310/93/105 | **DIAGNOSTIC ONLY** |
| 5 | reexpansion 0.05 top_1 | dflip+give0.33 | +0.0202 | **-0.1915** | +0.0784 | 140/44/52 | **REJECT** |

No policy is classified PROMISING or ADVANCE TO EVENT-DRIVEN VALIDATION.

### Detail — policy 3, the best-behaved of the five

`reexpansion(pullback=0.03, top_1)` → `direction_flip`, 1.0 ATR stop.

| Metric | Discovery | 2024 | 2025 |
|---|---:|---:|---:|
| Trades | 310 | 93 | 105 |
| Net ATR | +0.0245 | **-0.0748** | +0.0847 |
| Gross ATR | +0.0836 | -0.0249 | +0.1237 |
| Median ATR | +0.0933 | +0.0646 | +0.1242 |
| Win rate | 0.574 | 0.538 | 0.610 |
| Avg win / loss | +0.554 / -0.689 | +0.485 / -0.725 | +0.579 / -0.687 |
| MFE / MAE | 0.593 / 0.508 | 0.515 / 0.536 | 0.615 / 0.495 |
| Capture | +0.315 | +0.286 | +0.463 |
| Max drawdown | 17.4 | 11.8 | 5.8 |
| PnL share, largest 1% | 187% | -24% | 30% |
| Censored / ambiguous | 0 / 0 | 0 / 0 | 0 / 0 |

**Year decomposition kills it.** Within discovery: 2021 **-0.044**, 2022
**-0.030**, 2023 **+0.156**. The positive discovery aggregate is one year of
three. Direction: SHORT +0.039 / LONG +0.011 in discovery, but SHORT -0.106 /
LONG -0.047 in 2024 and SHORT -0.012 / LONG +0.173 in 2025 — no stable
direction. And the largest 1% of trades supply 187% of discovery PnL, meaning
the remaining 99% are collectively negative.

It fails five of the eight required robustness criteria.

---

## 6. Robustness and failure modes

| Criterion | Result |
|---|---|
| Adequate sample | Marginal. Best structures have 140–357 discovery trades, 44–105 per out-year. |
| Stability across years | **FAIL.** All six top composites negative in 2024. Best candidate positive in 1 of 3 discovery years. |
| Stability across directions | **FAIL.** No candidate holds sign across both directions in all periods. |
| Nearby-parameter stability | Partial. `reexpansion` is gross-positive across pullback 0.03/0.05/0.08 — a plateau — but the plateau sits below breakeven. |
| Single-month / outlier independence | **FAIL.** Largest 1% of trades supply 187% of discovery PnL on the best candidate. |
| Drawdown | Acceptable only because trade counts are small (5.8–17.4 ATR). |
| Censoring | **Clean — 0 censored** across all reported policies. |
| Same-bar ambiguity | **Clean — 0 ambiguous** across all reported policies. Conservative and optimistic bounds coincide. |

Dominant failure mode: **the loss side is untouched.** Every exit family that
improves capture or win rate does so by shrinking winners. Average loss stays
near -0.69 ATR regardless of exit, because losses are dominated by the stop, and
tightening the stop increases stop frequency faster than it reduces loss size.

---

## 7. Does anything reach +0.25 ATR net?

**No.** The best net expectancy observed on any period for any of 119 composites
is **+0.111** (policy 4, 2025 holdout, n=105) — and that same policy is
**-0.066** on 2024. On discovery, where sample sizes are largest, the maximum is
**+0.0439**.

There is no candidate in the +0.15 to +0.25 preservation band either. The best
sustained figure is roughly **+0.02 to +0.04 net on discovery only**, which
does not survive the selection year.

---

## 8. Recommended for NautilusTrader event-driven validation

**None.**

Advancing any of these to runtime validation would spend event-driven
engineering effort on a signal that is negative on its selection year and
outlier-dependent on its discovery years.

The one result worth carrying into future work is structural, not a policy:

> **Exit at thesis confirmation, not at the opposing flip.** `direction_flip` was
> the only gross-positive exit of 18 and halved drawdown. Any future study on
> this model pair should treat the confirming flip as the default exit and
> justify holding past it, rather than the reverse.

Second, `reexpansion` is the only entry family with coherent structure and is
worth re-testing **if the underlying models are retrained**. It is not worth
testing against these frozen models, where its edge is ~0.03 gross against a
0.06 cost.

---

## 9. Frozen policy contracts for finalists

Not issued. No finalist qualifies for advancement, so publishing a frozen
contract would imply a validation status that does not exist.

The two diagnostic policies are fully specified in
`results/stage3_composite.json` and reproducible from
`implementation/composite.py` (entry family, threshold, pullback, exit policy,
stop, and cost are all explicit fields).

---

## 10. Audit findings and unresolved limitations

### Defect found and fixed during this study — store

`canonical_regime_paths_all.parquet.session` was `"ETH"` on all 61,543,945 rows.
`polars dt.hour()` returns Int8, so `hour * 60` overflowed (8 × 60 = 480 → -32)
and the RTH window test was never true. Fixed by casting before multiplying;
session is recomputed at consolidation. Consolidation now asserts the
distribution is non-degenerate, and 17 regression tests cover the boundaries and
both DST transitions. Committed `7210923`.

Neither audit gate had caught it: the column was present, correctly typed, fully
non-null, and matched the SPEC field list. **Schema and provenance checks cannot
see a column that is uniformly wrong.**

### Defect found and fixed during this study — this engine

The first version of the simulator let trades run through the overnight gap.
Only RTH bars are loaded, so array index `i+1` after 14:59:59 is the *next
session's* 08:30:00; the horizon lookup landed there instead of stopping at the
session's last bar. One 2022-11-09 trade exited 2022-11-10 08:30 for +515 points
(+41.6 ATR) — against a discovery-set total of +17.18, meaning that single trade
was the entire apparent edge.

**Every Stage 1–3 result was inflated and has been recomputed.** Before/after on
the then-best candidate: net +0.0481 → **-0.0829**; largest trade +41.6 → +1.84.

Nothing flagged it: the outcome code read `SCORE_EXIT`, MFE was internally
consistent, `causal_lint` was clean, and the aggregate looked plausible. It
surfaced only because `pnl_share_largest_1pct` of 282% was implausible and the
individual trade was inspected. Six regression tests now pin session containment,
including a fixture with a +500 point gap that asserts no trade collects it.

### Validation performed

```text
backward parity      5,836 reproduced exactly (3,329 SHORT / 2,507 LONG,
                     by-year 1,147/1,206/1,187/1,149/1,147)
duplicate candidates 0
duplicate checkpoints 0
score cadence        true observations only; carry-forward lives on path rows
                     and cannot enter a persistence count
censoring            0 across all reported policies
same-bar ambiguity   0 across all reported policies
lifecycle            derived via next_start_after(ts, direction); no rule
                     references a literal R+1 / R+2
session containment  0 cross-session trades after the fix
```

### Unresolved limitations

- **2025 is not independent OOS.** Both frozen calibration populations are
  calendar-2025. Every threshold-based result inherits
  `THRESHOLD_OVERLAP_WAIVER.json`. The 2025 column above is descriptive only,
  and notably it is the *most* favourable period for several candidates — which
  is a reason for additional suspicion, not comfort.
- **Reentry was not tested to conclusion** (section 4).
- **Intraday-only by construction.** The forced 15:00 CT flat is a frozen user
  decision. It truncates the long favourable excursions that dominated the
  accepted overnight baseline, so these results are not comparable to the
  -0.067 / -0.097 ATR figures from `full_trade_path_builder`.
- **Sample sizes on the strongest structures are small** (140–357 discovery
  trades). A larger population requires a looser entry, and every looser entry
  tested was worse.
- **Cost sensitivity is not the binding constraint.** At zero cost the best
  entry is +0.034 gross and the best exit +0.011 gross. Even a frictionless
  world does not reach +0.25.

---

## Verdict

```text
NO CANDIDATE REACHES +0.25 ATR NET
```

- Best composite, discovery: **+0.0439 net**
- All six strongest composites: **negative on the 2024 selection year**
- Net-positive configurations: **0 of 47 entries, 0 of 18 exits**
- Highest-quality lower-EV candidate: `reexpansion(0.03, top_1) → direction_flip`,
  **DIAGNOSTIC ONLY** — retains structure across neighbouring parameters and has
  zero censoring and zero ambiguity, but is positive in one of three discovery
  years, negative in 2024, and 187% outlier-dependent.
- Recommended for event-driven validation: **none**
- Worth carrying forward: **exit at thesis confirmation rather than at the
  opposing flip**, and re-testing `reexpansion` only against retrained models.
