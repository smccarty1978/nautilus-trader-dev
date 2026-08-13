# P90 Entry Path × 5-Minute Regime Context — Report

**Verdict:** `M2_POST_CONFIRM_CONTEXT` (primary), secondary signals
`M2_POST_CONFIRM_CONTEXT`, `M3_TRANSITION_PATH_MATTERS`. 11/11 gates pass.
Full numeric facts: `results/summary.json`.

---

## Primary table

| metric | WITH_5M | AGAINST_5M |
|---|---:|---:|
| P90 arms | 1,268 | 7,682 |
| % population | 14.2% | 85.8% |
| P(confirm<1ATR) | 49.8% | 52.4% |
| median sec to confirm | 155 | 115 |
| MAE→confirm p50 | 0.330 | 0.330 |
| MAE→confirm p75 | 0.599 | 0.596 |
| MAE→confirm p90 | 0.809 | 0.820 |
| median return @ confirm | 1.011 ATR | 0.824 ATR |
| median eventual MaxMFE | 1.080 ATR | 0.978 ATR |
| P(MFE≥3ATR) | 20.5% | 18.7% |
| P(MFE≥4ATR) | 14.5% | 12.0% |
| baseline net ATR / P90 arm | +0.017 | −0.090 |
| MaxDD (ATR, cumulative curve) | 90.3 | 777.8 |

**Population is heavily skewed AGAINST_5M (85.8%).** P90 fade entries fire
against the prevailing 5-minute trend, not just the 5s/1m one — consistent
with the F4 finding that P90 is downstream of a short-term regime turn that
the 5-minute structure has not yet caught up to. Zero arms landed in UNINIT:
the 5-minute engine is warmed up for the entire 2021-2025 window.

## Transition matrix (confirming trades, n=4,656)

| transition | n | terminal return | P(MFE≥3ATR) | P(MFE≥4ATR) | flip-exit win rate |
|---|---:|---:|---:|---:|---:|
| WITH→WITH | 623 | 1.108 | 41.3% | 29.2% | 66.9% |
| WITH→AGAINST | 9 | 0.423 | 33.3% | 22.2% | 42.9% |
| AGAINST→WITH | **6** | 2.270 | 66.7% | 33.3% | 100% |
| AGAINST→AGAINST | 4,018 | 0.781 | 35.6% | 22.9% | 62.8% |

AGAINST→WITH looks best on every metric, but **n=6** — not remotely enough to
credit, flagged here explicitly rather than reported as a finding. The
comparison that matters is **WITH→WITH vs. AGAINST→AGAINST** (623 vs. 4,018
trades, both well-populated): WITH→WITH clears AGAINST→AGAINST by +0.33 ATR
terminal return and +5.6pp on P(MFE≥3ATR) — this is the entire basis for the
M2 verdict, and it **narrowly** clears the illustrative 5pp threshold
(0.056 vs. 0.05). Treat as a real but thin signal, not a strong one.

## Does 5m alignment predict CONFIRMATION? No.

`results/pre_confirm_outcome.csv`, `results/matched_stratified_control.csv`:
confirm-rate delta is **−2.5pp** (WITH_5M confirms *slightly less* often, not
more). Stratifying on year/side/time-of-day/`arm_score` quartile/1m-regime-age
barely moves it (raw −2.2pp → stratified −1.9pp), and the bootstrap CI
[−5.4%, +1.7%] includes zero. **M1 does not survive** — 5-minute alignment at
P90 is not an entry-selection signal.

## Does 5m alignment improve the 5s failure signal's specificity? No.

`results/five_m_x_5s_failure.csv`: PPV for eventual failure given a losing
adverse 5s flip is 0.667 (WITH_5M at the flip) vs. 0.682 (AGAINST_5M) —
a **1.5pp** difference, an order of magnitude below the 8pp bar for M4. 5m
context does not help distinguish the G4 study's false-positive 5s signals
from genuine failures.

## Is tighter risk more defensible in one context? Weak, if anything.

`results/stop_075_context.csv`: P(MAE>0.75 ATR among confirmers) is 13.3%
(WITH_5M) vs. 14.4% (AGAINST_5M) — a small difference in the *opposite*
direction of what would justify a tighter stop specifically AGAINST_5M.
Descriptive only; no stop distance was optimized here.

## Phase 6 (label-only) — not usable as a signal, shown for completeness

`results/phase6_timing.csv`. Arms where 5m eventually flips into the trade
direction BEFORE the trade's own terminal exit look spectacular (confirm
100%, mean MFE ~6 ATR, terminal return ~3-3.6 ATR) vs. arms with no such flip
(confirm 45.4%, MFE 1.12, terminal −0.63 ATR). **This is not a finding** — the
label is constructed from each arm's own outcome (a flip only counts if it
lands before that same trade's terminal exit), so strong trades are
mechanically more likely to have one. It answers a different, retrospective
question ("did the higher timeframe eventually turn during this trade's
life") and cannot be used causally at entry; kept isolated as
`label_only_`-prefixed columns for exactly this reason (SPEC section 5).

## Bottom line

5-minute regime context does **not** belong in entry selection (M1 fails
cleanly, CI includes zero) and does **not** sharpen the 5s failure signal
(M4 fails by an order of magnitude). It shows a real but **thin** post-confirm
signal (M2: WITH_5M confirmers run further, 0.33 ATR/+5.6pp on P(MFE≥3ATR)
vs. AGAINST_5M), and a suggestive-but-unreliable transition-path signal (M3)
resting on 6 trades that should not be acted on. If a follow-up study is
warranted, it is **context-specific runner management for already-confirmed
WITH_5M trades** (M2's next step per SPEC section 7) — not an entry filter,
not a tighter stop, not a revised 5s exit rule.
