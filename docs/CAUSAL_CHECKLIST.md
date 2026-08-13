# Canonical Causal Checklist (A1–H4)

**This file is the single source of truth for the causal audit ruleset.**

Every harness — Claude Code (`.claude/agents/`), Antigravity/Gemini
(`.agents/agents_staging/`), and Codex (`.codex/agents/`) — references *this
file* rather than restating the rules. Agent definitions that restate rules
drift; in July 2026 the Codex auditor was silently missing 14 rules, including
`C4` and `D4`, which were the #2 and #4 most frequent finding categories in the
repository. An audit that passed under one harness would fail under another.

`scripts/check_agent_parity.py` enforces that no agent definition restates the
ruleset. Change rules **here only**.

---

## SCOPE SPLIT — read this before auditing

Two different agents consume this file. They do **not** share scope.

| Agent | Owns | Must NOT report |
|---|---|---|
| `lookahead-auditor` | Sections **A, B, C1–C3, F, G, H** — causality, timestamps, look-ahead, train/serve skew | Missing deliverables, incomplete manifests, seal/tamper design, test quality, report wording |
| `contract-checker` | Sections **C4, D, E, plus the SPEC's Deliverables Manifest** — contract compliance, output completeness, seal integrity, reachability of terminal labels | Novel causal theories not already in the SPEC |

**Why the split exists.** Across ~100 historical audit reports, ~60% of blocking
findings were contract/deliverable-completeness (`D1` 22, `C4` 22, `C3` 12,
`D4` 9) rather than genuine look-ahead. Because the causal checklist has no
natural stopping point for completeness findings, the auditor invented new ones
each pass. One study
(`studies/codex_5.6_short_rth_enriched_volume_level_retrain/`) ran **18 audit
passes** and produced a 1,240-line append-only `audit.md`, almost entirely
`C4`/`D1` findings. Splitting the gate bounds each agent's search space.

If you are the `lookahead-auditor` and you notice a completeness problem, record
it in a single line under `## Referred to contract-checker` and move on. Do not
block on it, do not itemize it, and do not re-raise it on a later pass.

---

## A. NautilusTrader timestamp conventions

- **A1.** Bars use `b.ts_init` (close time, post `ts_init_delta` shift) — not
  `b.ts_event` (open time) — when indexing or stratifying.
- **A2.** When constructing `BarType` from raw Databento data, `ts_init_delta`
  shifts 1m bars +60_000_000_000 ns and 5m bars +300_000_000_000 ns. 1s bars
  need no adjustment.
- **A3.** Inside strategies, "current price" uses `self.cache.bar(bar_type)` or
  the `bar` argument to `on_bar`, never a future-indexed lookup.
- **A4.** Timer/alert callbacks (`on_event` for `TimeEvent`) do not assume bar
  data has already arrived for that timestamp.
- **A5.** Datetime conversion preserves close-time semantics. Resampling uses
  explicit `label`/`closed` arguments; `closed='right'` on a 1m resample of 1s
  bars injects look-ahead (see `catalog_1m_resample_bug`) — use `closed='left'`.

## B. Feature engineering look-ahead

- **B1.** Rolling computations (`rolling`, `ewm`, `expanding`) do not use
  `center=True`.
- **B2.** Indicator values used at bar `i` were computed using only data up to
  and including bar `i` — never bar `i+1`.
- **B3.** ATR, EMA and other recursive indicators are sampled at the correct bar
  — typically `i-1` or earlier when used as a feature for predicting bar `i`.
- **B4.** No `.shift(-N)` or negative-lag operations in the feature path.
- **B5.** Forward-fill does not leak future values into past timestamps. `bfill`
  is essentially always a bug in time-series features.
- **B6.** Joins/merges align on the correct boundary — `merge_asof` must carry an
  explicit `direction=` (normally `"backward"`).
- **B7.** Normalization statistics (z-score, scaling) come from a strictly past
  window, not the full dataset.
- **B9.** Feature trackers contain no undocumented or implicit timeframe
  assumptions. Window units, cadence, warmup and reset policy are explicit.
- **B10.** Multi-timeframe variants reuse the same verified tracker when the
  mathematical semantics are identical.

## C. Label construction

- **C1.** Labels use future windows *by design* — verify the look-ahead is
  **only** in label columns, never features.
- **C2.** Label timestamps align so the label at row `i` is what the model is
  asked to predict from features at row `i`.
- **C3.** Train/test splits are temporal, not random.
- **C4.** *(contract-checker scope)* Walk-forward validation does not refit on
  data overlapping the test window; selection seals authenticate their own
  selected result; promotion gates implement every frozen check.

## D. Train/serve skew *(contract-checker scope)*

- **D1.** Features computed offline match features computed live in the
  strategy's `on_bar`.
- **D2.** Filter cascades are trained on the *post-filter* distribution.
- **D3.** ONNX exports were made from the same model object whose features were
  validated.
- **D4.** Categorical encodings, missing-value imputation and feature ordering
  are deterministic and identical between train and serve.

## E. Backtest configuration *(contract-checker scope)*

- **E1.** Bar subscriptions in the strategy match the bar type produced by the
  data client.
- **E2.** `BarAggregation` and `PriceType` in `BarType` strings match the data
  being loaded.
- **E3.** Simulated venue uses an appropriate fill model — `LIMIT` orders do not
  auto-fill at signal price.
- **E4.** Order submission inside `on_bar` does not assume the bar that just
  closed is also the bar at which entry happens — entry occurs at the **next**
  bar's open.
- **E5.** Initial bar warmup for indicators is respected.

## F. Session and time handling

- **F1.** RTH/ETH classification uses bar **close** time, not open time. This is
  a repeat offender: `ts_event` in an RTH gate has been found in
  `studies/_shared_exit_mgmt/base_strategy.py:232` across multiple audits.
- **F2.** Session boundaries are explicitly handled — rolling windows spanning
  session boundaries either reset or are flagged.
- **F3.** Timezone handling is explicit. Naive timestamps are a red flag.
- **F4.** DST transitions do not break time-of-day filters. Use named zones
  (`America/Chicago`), never fixed UTC offsets.

## G. Data integrity

- **G1.** Continuous-contract data is back-adjusted at quarterly rolls, or rolls
  are handled explicitly. Only `*.v.0` (volume-continuous) data is permitted.
- **G2.** Missing bars are handled — neither forward-filled with stale prices nor
  silently dropped.
- **G3.** When 1s data is resampled to 1m, the resampler uses correct
  `label`/`closed` arguments and drops empty minutes.
- **G4.** Volume-zero or single-tick bars are not used to compute indicators.

## H. Offline bracket simulation price resolution

- **H1.** SL/PT detection uses bar **HIGH and LOW**, not close.
- **H2.** Temporal resolution matches NT execution. Flag any sim iterating over
  bars coarser than 1s when the NT strategy monitors stops on 1s bars.
- **H3.** Re-entry logic matches the NT strategy's re-entry rules.
- **H4.** Fill price is the actual next-bar open or NT-reported fill — **not** the
  trigger price. Flag any sim computing
  `exit_pnl = (sl_px - entry_px) * direction * MULT`. This is the single most
  repeated finding in repository history (8 occurrences).

---

## Severity definitions

| Severity | Meaning | Gate effect |
|---|---|---|
| `CRITICAL` | Demonstrated defect that changes results, or an unenforced invariant the study's conclusion depends on | Blocks |
| `WARNING` | Real defect that does not change the headline result, or an enforced-in-practice-but-not-in-code invariant | Blocks unless explicitly adjudicated in the SPEC |
| `NOTE` | Disclosure, hygiene, or inherited upstream limitation | Does not block |

A finding is `CRITICAL` only if you can state a concrete failure path. "This is
not independently validated" is a `WARNING` unless you can show the validation
would fail.
