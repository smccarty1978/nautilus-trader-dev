# Confirmation Economics + Post-Confirmation Excursion Map — Frozen Specification

**Study:** `confirmation_economics_excursion_map`
**Substrate:** `data/canonical/regime_complete_v1/` (REGIME-COMPLETE STORE ACCEPTED)
**Frozen:** 2026-08-10, before implementation.

---

## 0. Objective and posture

Establish the **economic geometry** of a fade trade after the predicted regime
flip occurs, so that management rules can later be designed from evidence.

> Once our predicted flip actually occurs, what risk does a healthy future runner
> genuinely require, and how much can we tighten without destroying the right tail?

**This is a diagnostic study.** No exit grid, no trailing-stop optimization, no
search for the best backtest. It may not conclude with a tuned parameter. If the
geometry supports management research, a *later* study tests a small number of
policies.

---

## 1. Frozen contract

Inherited unmodified from the accepted studies. This study defines no second
version of any of them.

```text
entry timestamp    checkpoint_decision_ns of the qualifying score checkpoint
entry price        checkpoint_reference_price at that checkpoint
ATR anchor         atr_at_checkpoint at ENTRY, frozen for the whole trade;
                   every excursion in this study is normalised by it
initial stop       1.0 ATR adverse excursion from entry price, detected on a
                   completed 1s bar, filled at the FOLLOWING bar's open;
                   the trigger price is never credited
confirming flip    RegimeIndex.next_start_after(entry_ns, direction, inclusive=True)
confirm price      the CLOSE of the 1s bar at the confirming flip
opposing flip      next_start_after(entry_ns, -direction, inclusive=True)
session            RTH only, forced flat 15:00 CT, window clamped to the entry's
                   own session -- no overnight stitching
cost               2 ticks round-turn = 0.50 points, charged per completed trade
flat band          |return| < 0.125 points reported flat
direction          +1 LONG (bearish model in-domain) / -1 SHORT (bullish in-domain)
```

`inclusive=True` is mandatory. A regime flip stamped at second T is knowable only
after a decision made at T under the 1s-before-1m dispatch convention; the
superseded strictly-after resolver mis-resolved ~2% of trades.

### 1.1 Intrabar / same-bar ordering

1s OHLC does not reveal intrabar sequence and **no ordering is inferred**. A bar
that could satisfy both an adverse and a favorable trigger is:

- resolved **adversely** for the reported (conservative) bound,
- flagged `ambiguous`,
- and counted, with the optimistic bound reported alongside.

This applies to stop-vs-confirm, stop-vs-landmark, and floor-vs-landmark
collisions alike.

---

## 2. Two path modes, never conflated

Every trade is walked **twice**. Each result row carries `path_mode`.

| | `constrained` | `unconstrained` |
|---|---|---|
| 1.0 ATR entry stop | **live** | **removed after confirmation** |
| Drives | Phases 1, 2, 8; all canonical terminal labels | Phases 3–7 excursion and survival maps |
| Question answered | what the real strategy did | what the price path does naturally once the flip occurs |

**Why both.** `CONFIRMED_THEN_STOPPED` only exists as a label if the stop is
live, so Phases 1/2/8 require the constrained walk. But with the stop live,
post-confirmation adverse excursion is *mechanically capped* at 1 ATR from entry,
so "how much room does a ≥3 ATR runner need" would be answered by its own
premise. That is the censoring trap that understated p90 MAE by 5× in
`armed_fade_score_path_progression`; see
[[censored_population_cannot_answer_its_own_premise]] in the project record.

`terminal_label_constrained` is carried on **both** rows so any table can group by
the canonical outcome regardless of the mode it measures.

---

## 3. Populations

### 3.1 Base — four, reproduced exactly

The accepted `first_qualifying`-after-600s rule from
`studies/model_driven_entry_exit_discovery/results/regime_lifecycle_600s.json`:
the first in-domain checkpoint at or above the threshold whose regime age at that
checkpoint already exceeds 600s.

| Level | Required count |
|---|---:|
| `top_10` | **8,988** |
| `top_5` | **7,396** |
| `top_2_5` | **5,823** |
| `top_1` | **3,415** |

Reproducing these exactly is a **gate**, not a check (§9 gate 1). A different
population may not be introduced silently.

### 3.2 Additional — the armed population

`studies/armed_fade_score_path_progression/` (accepted, verdict ARMED SCORE
PROGRESSION SUPPORTS REFINEMENT): the first true Top-10 crossing **from below**
after 600s, **8,950** regimes. Included as a fifth, **additional** population. It
does not replace any base population.

### 3.3 Depth

| Population | Phases |
|---|---|
| `top_2_5` (accepted baseline) | **all**, 1–9 |
| `armed` | **all**, 1–9 |
| `top_10`, `top_5`, `top_1` | 1, 2, 4, 8 + the Gate A/B answers, as a stability annex |

### 3.4 Terminal label mapping

The base populations' accepted lifecycle uses different names from the armed
study's continuation walk. They are the same events:

```text
STOPPED_BEFORE_CONFIRM  ==  (not confirmed; excluded from this study)
STOPPED_AFTER_CONFIRM   ==  CONFIRMED_THEN_STOPPED          (A)
REGIME_FLIP_EXIT        ->  FINAL_FLIP_EXIT_WINNER / _LOSER (C / B, split on sign)
SESSION_CLOSE           ==  SESSION_EXIT                    (D)
```

The armed population's counts are **822 / 1,359 / 2,350 / 174**. Those belong to
the armed population only and are recomputed independently per base population.

---

## 4. Phases

**Phase 1 — confirmation economics.** For trades reaching the confirming flip
before the 1 ATR stop, at the confirming flip **bar close**: return from entry,
MFE entry→confirm, MAE entry→confirm, and giveback (`pre-confirm MFE − return at
confirm close`), each as mean / median / p10 / p25 / p50 / p75 / p90 / p95. Plus
% positive, % ≥ +0.25 / +0.50 / +0.75 / +1.00 ATR, % below zero.

**Phase 2 — outcome split.** Same economics broken out by terminal outcome A/B/C/D
and by eventual achieved MFE bucket (`<1.0 · 1.0–1.5 · 1.5–2.0 · 2.0–2.5 ·
2.5–3.0 · ≥3.0 ATR`), plus seconds entry→confirmation.

**Phase 3 — post-confirmation risk map.** `t = 0` at the confirming flip bar
close. For each **entry-relative** MFE landmark `+0.50 / +0.75 / +1.00 / +1.25 /
+1.50 / +2.00 / +2.50 / +3.00 ATR`, among trades that subsequently reach it,
report n / median / p75 / p90 / p95 / max of the post-confirmation adverse
excursion, measured **two ways that are never conflated**:

- **A, from confirmation close** — `confirm_close − subsequent_low` (LONG) or
  `subsequent_high − confirm_close` (SHORT), direction-normalised, in frozen-entry ATR.
- **B, from the running favorable extreme** — giveback from the best favorable
  price achieved so far.

**Landmarks already achieved at confirmation are excluded from the landmark's
distribution and counted separately.** Median return at confirmation is ≈0.85 ATR
in the armed population, so +0.50 and +0.75 are usually already held at `t = 0`;
folding those in as a zero retrace would fabricate the top rows of the table.
Only *first achievement strictly after confirmation* counts.

**Phase 4 — runner survival curve.** Inverted. For post-confirmation
deterioration levels `0.25 / 0.375 / 0.50 / 0.625 / 0.75 / 1.00 ATR`, the share of
all confirmed trades, eventual losers, eventual flip-exit winners, and ≥2 / ≥2.5 /
≥3 ATR runners that touch each level before their relevant favorable development.
**This is a separability map, not a stop backtest.**

**Phase 5 — conditional on profit at confirmation.** Buckets `<0 · 0–0.25 ·
0.25–0.50 · 0.50–0.75 · 0.75–1.00 · ≥1.00 ATR`. Per bucket: P(stop), P(losing flip
exit), P(positive flip exit), P(≥1.5 / ≥2 / ≥2.5 / ≥3 ATR MFE), and the
post-confirm adverse excursion distributions.

**Phase 6 — profit-floor feasibility.** Entry-relative floors `−0.25 / 0.00 /
+0.25 / +0.50 / +0.75 ATR`, evaluated **only where the floor is below the open
profit at confirmation** and could therefore actually be placed. Report failures
intercepted, flip-exit losers intercepted, and winners / ≥2 / ≥2.5 / ≥3 ATR
runners touched. Feasibility map, not a policy.

**Phase 7 — runner development map.** Landmarks `+1.0 / +1.5 / +2.0 / +2.5 / +3.0
ATR`. The clock resets at the **first causal achievement** of each landmark. Then:
additional MFE subsequently achieved; giveback from the running favorable extreme
before reaching the next landmark; and giveback before final exit when the next
landmark is never reached. Transition probabilities `P(+1.5 | +1.0)`,
`P(+2.0 | +1.5)`, `P(+2.5 | +2.0)`, `P(+3.0 | +2.5)`, with giveback distributions
split by successful vs failed transition.

**Phase 8 — regime-flip exit efficiency.** For trades reaching the final opposing
flip: capture ratio `realized return / max MFE` (guarded for near-zero MFE, which
is reported separately rather than divided through), and absolute ATR giveback
`max MFE − realized return`. Split by final winner/loser, MFE bucket, and entry
threshold. Then, arithmetically from the actual population, the share of MFE that
would have to be captured to lift expectancy by +0.05 / +0.10 / +0.15 / +0.25
ATR per trade.

> **Expectancy denominator: ALL entries in the population**, including trades
> stopped before confirmation — the only denominator comparable to the strategy's
> real expectancy. Confirmed-only and flip-exit-only denominators are reported
> alongside, and the report states explicitly what fraction of entries a better
> runner exit can even reach.

**Phase 9 — model overlay, EXPLORATORY OUT-OF-DOMAIN.** The gate is satisfied:
`studies/post_confirmation_score_deterioration/reconciliation/` (verdict **B**)
established the raw post-confirmation score is a true dispatch, causally available
at its decision timestamp (`*_score_is_new` true for 100% of rows;
`*_score_available_ns − checkpoint_decision_ns == 0` for all 5,665,103 RTH rows),
with domain status explicitly quantified: contract-valid in-domain share is
**0.0% / 0.0% / 1.6% / 16.4%** at 60 / 120 / 180 / 300s.

The overlay therefore runs, and **every table it produces is labelled exploratory
out-of-domain and not deployable.** It asks only whether model danger improves the
price-only separation found above, at a small number of economically meaningful
price states. No optimization, no grid. Frozen score landmarks only.

---

## 5. Causality

- Every landmark is a **first causal achievement**; no future extremum triggers it.
- Subsequent excursion is measured **only after** the landmark.
- Completed 1s bar semantics throughout; no interpolation.
- Exact session containment; no overnight stitching.
- No future regime label is used as a predictor. Terminal labels are used
  **retrospectively for grouping only**.
- Same-bar collisions resolved per §1.1, never by inferred ordering.

---

## 6. Deliverables Manifest

Frozen before implementation; the completion gate checks it literally.

| # | Path | Contents |
|---|---|---|
| 1 | `SPEC.md` | this document |
| 2 | `README.md` | reproduce steps, module map, the two path modes, the population table |
| 3 | `REPORT.md` | the eleven executive questions, the phase sections, Gates A and B, ending in exactly one §7 label |
| 4 | `results/excursion_panel.parquet` | the per-(trade, path_mode) panel (gitignored; manifest committed) |
| 5 | `results/confirmation_economics.json` | Phase 1 |
| 6 | `results/confirmation_outcome_breakdown.json` | Phase 2 |
| 7 | `results/post_confirmation_excursion_map.json` | Phase 3, both measurement methods |
| 8 | `results/runner_survival_curve.json` | Phase 4 |
| 9 | `results/confirmation_profit_conditioning.json` | Phase 5 |
| 10 | `results/profit_floor_feasibility.json` | Phase 6 |
| 11 | `results/runner_landmark_transitions.json` | Phase 7 |
| 12 | `results/regime_flip_exit_capture_efficiency.json` | Phase 8 |
| 13 | `results/price_model_overlay.json` | Phase 9 |
| 14 | `results/validation_report.json` | the §9 gates, each with `passed`, plus `all_passed` |
| 15 | `results/partition_manifest.json` | conventions, populations, landmarks, code hashes |
| 16 | `audit/lint.json`, `audit/status.json`, `audit/contract_status.json` | gate verdicts |

## 7. Terminal classification

Exactly one. All reachable.

| Label | Condition |
|---|---|
| **A** `CONFIRMATION DOES NOT CREATE A USEFUL RISK-RESET OPPORTUNITY` | no post-confirm deterioration level separates eventual failures from runners better than chance |
| **B** `CONFIRMED LOSERS CAN POTENTIALLY BE CONTAINED WITHOUT MAJOR RUNNER DAMAGE` | a deterioration region catches a materially larger share of failures than of ≥2.5 ATR runners, and Gate B finds exit capture already efficient |
| **C** `SIMPLE RISK RESET DAMAGES TOO MANY RUNNERS; CONDITIONAL MANAGEMENT IS REQUIRED` | no unconditional level separates, but conditioning on profit-at-confirmation or runner maturity does |
| **D** `RUNNER GIVEBACK IS THE PRIMARY ECONOMIC OPPORTUNITY` | Gate A fails or is marginal while Gate B finds substantial recoverable giveback |
| **E** `BOTH CONFIRMED-LOSS CONTAINMENT AND RUNNER HARVESTING WARRANT BOUNDED POLICY STUDIES` | Gates A and B both pass materially |
| **F** `RESULTS INCONCLUSIVE / CONTRACT FAILURE` | a §9 gate fails, so absence of a finding cannot be distinguished from absence of a valid measurement |

## 8. Domain and completeness

| Dimension | Domain | Rule |
|---|---|---|
| Instrument | NQ `*.v.0` | anything else is out of scope, not missing |
| Years | 2021–2025 | 2026 forbidden; a missing year is a defect |
| Session | RTH only | forced flat 15:00 CT |
| Populations | the five in §3 | base counts reproduced exactly or the verdict is F |
| Path modes | exactly the two in §2 | never pooled; every row carries `path_mode` |
| Landmarks / floors / deterioration levels | exactly those in §4 | no tuned value, no added level |
| 2025 | **NOT threshold-OOS** | inherited disclosure, kept visible; canonical waiver `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json` |
| Ambiguity | counted, both bounds | §1.1 |

## 9. Validation

To `results/validation_report.json`, each with `passed`, plus `all_passed`.

```text
 1  population_parity        8,988 / 7,396 / 5,823 / 3,415 reproduced exactly; armed 8,950
 2  confirmation_parity      confirmed counts reconciled against the accepted
                             lifecycle survival figures
 3  independent_recompute    >= 200 deterministic trade paths re-derived by a
                             separate code path from the raw 1s parquet
 4  entry_to_confirm_parity  MFE/MAE entry->confirm agree with the independent walk
 5  confirm_close_parity     confirm close price matches the raw 1s source bar
 6  landmark_first_touch     every landmark timestamp is the FIRST causal touch
 7  session_containment      no observation or event past the session close
 8  no_overnight_stitching   no path spans a session boundary
 9  direction_normalization  synthetic LONG and SHORT cases give mirror results
10  same_bar_accounting      ambiguous collisions counted; both bounds reported
11  audit_gates              causal_lint clean; lookahead-auditor and
                             contract-checker verdicts machine-read
```

A **pre-execution** `causal_lint` + `lookahead-auditor` pass runs on the new
lifecycle/matching logic before the first full run.

## 10. Non-goals

No exit grid, no trailing-stop optimization, no parameter sweep, no policy
recommendation, no retraining, no feature or regime redefinition, no new
threshold, no 2026 data, no modification of the canonical store or any accepted
upstream artifact, and no recollection of 1s data.
