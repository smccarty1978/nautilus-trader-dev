# CHECKPOINT — post_confirmation_score_deterioration

**STUDY COMPLETE — committed `9f2033f` on `study/post_confirmation_score_deterioration`.**
Terminal label **B**. All 9 validation gates pass; all three audit gates clean.
Phase 8 deliberately not run, per the brief's stop rule. Nothing is outstanding.

The remaining-work list at the foot of this file is **done**. History below is
kept as the decision trail, including two of my own errors that the process
caught (the stream A/B conflation, and the runner-damage estimate the ledger
overturned).

**Last updated:** 2026-08-10 ~02:15 CDT

Read this first on resume. It records what is established, what was decided and
why, and what is next. Everything below is reproduced from artifacts under
`results/`, not from memory.

---

## Status

| Phase | State |
|---|---|
| 0 — repo/contract review, feasibility probes | **DONE** |
| Gate 1 — does post-confirm score separate failures? | **PASS** — availability re-verified, see below |
| SPEC frozen | **DONE** — `SPEC.md` |
| 1 — post-confirmation panel | **DONE** — `results/post_confirm_paths.parquet` |
| 2–7, Gate 2, 8 | in progress |

Artifacts: `results/phase0_probe.json`, `phase0_probe2.json`, `phase0_gate1.json`,
`stream_b_coverage.json`, `post_confirm_paths.parquet`, `partition_manifest.json`,
`population_reconciliation.json`.
Code: `implementation/phase0_probe.py`, `phase0_probe2.py`, `phase0_gate1.py`,
`build_panel.py`.

**Panel:** 658,331 rows over 4,656 trades. The 49 trades absent from the panel
are exactly the Walk A `SESSION_CLOSE_UNRESOLVED` set folded into `SESSION_EXIT`
(174 − 125 = 49) — consistent, not a defect. Rebuild takes ~4 min; it is
gitignored, so do NOT delete it casually.

**Nothing is committed yet. No REPORT/README written yet.**

---

## Established facts

### Population reconciles EXACTLY against the brief

From `studies/armed_fade_score_path_progression/results/armed_regime_score_paths.parquet`
(8,950 armed regimes, `valid` only):

```text
CONFIRMED_THEN_STOPPED    822   (brief said 822)  MATCH
FINAL_FLIP_EXIT_LOSER   1,359   (brief said 1,359) MATCH
FINAL_FLIP_EXIT_WINNER  2,350   (brief said 2,350) MATCH
SESSION_EXIT              174   (brief said 174)   MATCH
STOPPED_BEFORE_CONFIRM  4,245
```

Confirmed via continuation walk = 4,705; via Walk A = 4,656; **delta 49 = exactly
Walk A's `SESSION_CLOSE_UNRESOLVED`**, which the continuation walk folds into
`SESSION_EXIT`. Fully explained, no unreconciled residual.

New-regime join: 4,705 of 4,705 matched (join on
`regime_start_decision_ns == walk_a_confirm_ns AND regime_direction == direction`).
Zero unmatched.

### Hold time after confirmation, by outcome

| label | n | median hold s | p25 | p75 | median MFE ATR |
|---|---:|---:|---:|---:|---:|
| FINAL_FLIP_EXIT_WINNER | 2,350 | 960 | 600 | 1,440 | 3.67 |
| FINAL_FLIP_EXIT_LOSER | 1,359 | 300 | 180 | 480 | 1.48 |
| CONFIRMED_THEN_STOPPED | 822 | 217.5 | 115 | 349 | 1.05 |
| SESSION_EXIT | 174 | 419 | −1 | 779 | 3.56 |

**"Failure" is largely "the new regime was short-lived."** Keep this in view — it
makes some of the predictive power near-definitional, so the economic questions
(Phases 4–5) are what decide the study, not the AUC.

### THE POLARITY IS INVERTED RELATIVE TO THE BRIEF

The brief frames deterioration as the score **falling**. It is the opposite.

Confirmed empirically (`phase0_probe.json`, rate = 1.0): `bullish_in_domain` is
true exactly when `regime_direction == +1`. After confirmation we hold a position
**aligned with** the new regime (fade a bullish regime SHORT → confirmation is a
bearish regime → we are short in a bearish regime). The model whose domain is the
new regime therefore predicts **that regime's own flip** — i.e. the end of our
position.

```text
domain-model score RISING  = our regime is likely ending = DANGER
domain-model score FALLING = our regime is persisting    = RUNNER
```

Every event definition in the brief ("score retreat >= 0.03", "loss of Top-1")
must be **sign-flipped** for the domain-model stream, or the study will measure
the exact opposite of what it intends. Document prominently in SPEC and REPORT.

### THREE score streams, not one — and the distinction matters

I initially conflated two of these and got the feasibility verdict wrong for
about twenty minutes. The `*_in_domain` flag is a **contract gate** (may this
score qualify a trade?), not an **availability gate** (does a number exist?).

| Stream | Definition | Coverage on FAILED trades | Usable? |
|---|---|---:|---|
| **A. In-domain-flagged** | score where `bullish_in_domain`/`bearish_in_domain` is true | **7.7%** (169 of 2,181) | **NO — fatal selection bias** |
| **B. Domain-model raw** | `bullish_probability` if new regime dir +1 else `bearish_probability`, ungated | ~97% | **YES — primary candidate** |
| **C. Other-model raw** | the opposite column, exploratory | ~100% | secondary |

**Stream A is dead and the reason is structural.** The established-regime gate
opens a median **352–448s** after confirmation, while failed trades die at a
median **217–300s**. So:

```text
CONFIRMED_THEN_STOPPED  95.7% of trades: gate NEVER opens before exit
                        median gate delay = 197% of the trade's whole duration
FINAL_FLIP_EXIT_LOSER   90.1% never opens before exit
FINAL_FLIP_EXIT_WINNER  only 30.6% never opens
```

Availability is determined by the outcome. Any analysis on stream A compares 159
failures against 1,628 winners on a population selected by having survived long
enough to be scored. **Do not resurrect stream A.**

> **RE-VERIFIED — DONE, stream B holds.** `results/stream_b_coverage.json`.
> Over all 5,665,103 RTH score rows, a probability is present at 91.5–92.2%
> **regardless of the in-domain flag** (bullish: 91.46% out-of-domain vs 92.23%
> in-domain; bearish: 91.95% vs 91.61%). The ~8% of nulls are feature
> incompleteness, not gating. Per-trade coverage in the post-confirmation window:
>
> | label | total | ≥1 obs | ≥3 obs | median obs |
> |---|---:|---:|---:|---:|
> | FINAL_FLIP_EXIT_WINNER | 2,350 | **100%** | 100% | 179 |
> | FINAL_FLIP_EXIT_LOSER | 1,359 | **100%** | 100% | 59 |
> | CONFIRMED_THEN_STOPPED | 822 | **100%** | 99.64% | 41 |
> | SESSION_EXIT | 174 | 71.8% | 71.8% | 119 |
>
> **All 2,181 failed trades have ≥1 observation; 2,178 have ≥3.** No selection
> bias. Gate 1 is a full PASS on both information content and availability.

---

## Gate 1 result (provisional): PASS on information content

Landmark design — state evaluated at a **fixed elapsed time from confirmation**,
among trades **still open** at that time. AUC target = failure
(`CONFIRMED_THEN_STOPPED` + `FINAL_FLIP_EXIT_LOSER`) vs `FINAL_FLIP_EXIT_WINNER`.
0.50 = no information.

This design is non-negotiable. Path summaries over a window ending at the
terminal event are confounded with duration, which has now corrupted a result in
this research line **twice** — the shape classes in the predecessor study, and in
probe 1 of this study, where winners' higher peak score (0.540 vs 0.331) was
almost entirely an artifact of observing them for 111 dispatches versus 16.

**Stream B — domain-model raw score:**

| horizon | n | fail / win | base rate | AUC `last` | AUC `peak` | AUC `delta from first` |
|---|---:|---|---:|---:|---:|---:|
| 60s | 4,471 | 2,121 / 2,350 | 0.474 | 0.684 | 0.655 | 0.659 |
| 120s | 4,283 | 1,933 / 2,350 | 0.451 | 0.735 | 0.683 | 0.706 |
| 180s | 3,795 | 1,475 / 2,320 | 0.389 | 0.753 | 0.686 | 0.712 |
| 300s | 3,117 | 884 / 2,233 | 0.284 | 0.780 | 0.720 | 0.723 |

Rising, monotone in horizon, on near-complete coverage. Direction confirms the
polarity finding: **higher domain-model score → failure**.

**Stream C — other-model raw score:** AUC `last` 0.31 → 0.29 (i.e. 0.69–0.71
inverted: higher → winner), and AUC `retreat_from_peak` 0.66–0.68. Informative
but a mirror of B; treat as secondary/corroborating.

---

## Phase 4–7 findings so far

### NEGATIVE: path-threshold escalation events are useless here

`results/deterioration_event_table.json`. Every escalation event fires on
essentially the whole population:

```text
ESCALATION_0_03_from_min   fired 4,529/4,531  sens 0.999  winner touch 1.000  prec 0.481
ESCALATION_0_10_from_confirm fired 4,472/4,531 sens 0.984 winner touch 0.990  prec 0.480
STREAMC_RETREAT_0_05       fired 4,528/4,531  sens 0.999  winner touch 1.000  prec 0.481
```

Precision equals the base failure rate (0.481) exactly — **zero information**.
Cause: over 41–179 dispatches the score is near-certain to rise 0.03–0.10 off its
running minimum at some point. "Did the score ever escalate" is always yes. Do
not revisit; the Gate 1 signal is in the score **level at a fixed time**, not in
path crossings.

`DIVERGENCE_price_high_score_high` fired on only 157 trades with precision
**0.338 — below the 0.481 base rate**, i.e. it weakly predicts *winners*. Phase 3
as specified is a null.

### Gate 2 trade-off curve exists and discriminates

`results/landmark_tradeoff.json`. Landmark + score-level quantile sweep. Example
operating points:

| t | q | sens | winner touch | touch ≥2.5 ATR | precision | median open PnL at flag | median remaining MFE, winners touched |
|---|---|---:|---:|---:|---:|---:|---:|
| 120s | 0.70 | 0.449 | 0.177 | 0.162 | 0.676 | −0.63 | 2.69 |
| 120s | 0.85 | 0.250 | 0.068 | 0.060 | 0.753 | −0.86 | 3.00 |
| 300s | 0.85 | 0.319 | 0.083 | 0.071 | 0.603 | −0.64 | 1.86 |
| 600s | 0.95 | 0.200 | 0.029 | 0.026 | 0.500 | −0.31 | 0.40 |

Discrimination is real (precision 0.68–0.84 vs base 0.45). **But the economics
look hostile:** at every early landmark the median open PnL when the flag fires
is already **negative** (−0.20 to −1.04 ATR), while each winner touched still had
**1.0–3.6 ATR of MFE ahead of it**. Order-of-magnitude at t=120s/q=0.85: ~484
failures saved perhaps ~0.2 ATR each versus ~159 winners forfeiting ~3.0 ATR
each — roughly 97 ATR saved against ~477 ATR destroyed.

**The late window (t=600s) is the only region where remaining MFE is small
(0.40 ATR at q=0.95), and there only 245 failures are still alive to catch.**

### GATE 2 LEDGER: net POSITIVE — and then killed by the placebo

`results/gate2_ledger.json`. My order-of-magnitude estimate above was **wrong**,
and the reason is worth keeping: I conflated *remaining MFE* (the peak a winner
would still reach) with *PnL forgone* (exit-now minus realized exit). Winners
give back most of their MFE by the opposing flip, so ejecting one early costs far
less than its remaining MFE implies. The true ledger is net positive nearly
everywhere: +246 ATR at t=60s/q=0.50, +144 at t=300s/q=0.70, +29 at
t=600s/q=0.95. Only one negative point (t=180s/q=0.95, n=190).

**`results/placebo.json` shows this is entirely non-specific.** Two matched
controls at every operating point:

```text
RANDOM      flag a random subset of the same size (400 draws)
WORST_PNL   flag the k trades with the most negative open PnL at the landmark
```

Result across all 25 operating points:

- **Zero** exceed the random p95. Score percentile vs the random distribution
  runs 0.08–0.87, median ≈0.55 — dead centre. At t=180s/q=0.50 the score returns
  +78 ATR against a random mean of **+156**.
- The score loses to plain WORST_PNL ranking at **11 of 25** points, wins at 14,
  with no pattern in horizon or quantile.

**The whole net-positive result is "exiting early beats holding to the opposing
flip".** That is the predecessor study's own conclusion re-derived, not new
information, and it is the exact failure mode that killed
`contextual_runner_exit_v3_investigate` (stop timing fails placebo). The AUC 0.78
is real as *prediction* and worthless as *management*.

### TERMINAL CLASSIFICATION: **B**

`POST-CONFIRMATION SCORE PREDICTS FAILURE BUT TOO LATE TO MONETIZE`

Not A — separation is real and strong (AUC 0.684→0.780; precision 0.68–0.84 vs a
0.45 base). Not C — runner damage was tolerable in the ledger. Not D/E — the
placebo removes the entire economic case. Median open PnL when the flag fires is
already **−0.20 to −1.04 ATR**: the position is underwater before the signal
appears, and acting on it is no better than acting at random.

**Per the brief, STOP. Do not run Phase 8.**

> ~~**NEXT (decisive): the Gate 2 ATR ledger.**~~ DONE — see above.
> <details><summary>original note</summary> Compute, per (horizon, quantile),
> the true counterfactual: for every flagged trade, `open_pnl_at_flag −
> final_realized_pnl` in confirmation-anchored ATR, summed over failures (saved)
> and winners (destroyed). Confirmation-anchored terminal PnL is derivable from
> the panel: `exit_price = arm_price + full_gross_atr * arm_atr * direction`,
> then re-anchor to `confirm_price` / `atr_at_confirmation`. Note the predecessor's
> 0.125-point flat band when reconstructing. This number decides between terminal
> labels **B** (too late) and **C** (damages runners) — current evidence points at
> **C**, possibly **B**, and almost certainly not D/E.
> </details>

## Remaining work to close the study

1. `REPORT.md` — executive summary answering the brief's 7 questions, then the
   phase sections, ending in terminal label **B**.
2. `README.md` — module map, the three streams, the polarity warning.
3. `implementation/validate.py` → `results/validation_report.json`, the nine
   SPEC §9 gates.
4. `causal_lint` → `lookahead-auditor` → `contract-checker`.
5. Branch `study/post_confirmation_score_deterioration`, then commit code +
   audit + JSON results. **Gitignore `results/*.parquet`.**

## Decisions taken (conservative reading, per the brief's instruction)

1. **Primary stream = B (domain-model raw), with the contract caveat stated in
   full.** It is causally available at runtime — the number is computed from
   features at that timestamp — but the model is being read outside its
   contractual domain, so **the frozen percentile thresholds do NOT apply to
   it.** Consequence: brief events phrased as "loss of Top-1 / Top-2.5 / Top-5 /
   Top-10" **cannot be evaluated on stream B** without inventing new thresholds,
   which would be a second incompatible threshold definition and is forbidden by
   Phase 0 rule 4. Report those events as **NOT APPLICABLE with the reason**, and
   use distribution-free constructions (retreat/escalation magnitudes in raw
   probability units, and within-trade relative moves) instead.
2. **Landmark analysis only**, per above.
3. **Failure = A + B (CONFIRMED_THEN_STOPPED + FINAL_FLIP_EXIT_LOSER)**;
   `SESSION_EXIT` excluded from the AUC target (it is an artifact of the intraday
   constraint) but reported separately as required.
4. **2025 is NOT threshold-OOS** — inherited disclosure, keep visible.
5. **2026 untouched.**

---

## Next steps, in order

1. **Re-verify stream B availability** (see box above). Gate 1 is provisional
   until this passes.
2. Write `SPEC.md` with: the polarity inversion, the three streams and why A is
   dead, the landmark design, the NOT-APPLICABLE threshold events and why, the
   deliverables manifest, and terminal labels A–E from the brief.
3. Phase 1: build the post-confirmation panel as a checkpointed parquet
   (`results/post_confirm_paths.parquet`) — one row per (trade, dispatch), with
   price, excursions, open PnL in ATR, running MFE/MAE, both score streams.
   Reuse `arm_atr` (ATR frozen at arm) **and** record ATR at confirmation; state
   which is used where.
4. Phases 2–3: escalation/retreat features and price-vs-score divergence, all
   landmark-evaluated.
5. Phase 4–5: economic state at event, and runner-touch rates by MFE bucket
   (<1, 1–2, 2–2.5, 2.5–3, >=3 ATR). **Gate 2 lives here.**
6. Phase 6 event table, Phase 7 stability, then Gate 2 decision.
7. Only if both gates pass: the small Phase 8 policy simulation.
8. `causal_lint` → `lookahead-auditor` → `contract-checker`; commit on a new
   branch `study/post_confirmation_score_deterioration`.

## Budget notes

- Currently on branch `study/armed_fade_score_path_progression`. **Create the new
  branch before committing.**
- Predecessor parquet (`armed_regime_score_paths.parquet`) is gitignored and
  regenerable; it exists locally now. Do not rebuild it — it takes ~7 min.
- The score parquet is 12.2M rows; filter to `session == "RTH"` and join to the
  4,705 confirmed trades before doing anything per-row.
- No subagents used yet. Use `lookahead-auditor` once, at the end, on the final
  causal logic — not on the probes.
