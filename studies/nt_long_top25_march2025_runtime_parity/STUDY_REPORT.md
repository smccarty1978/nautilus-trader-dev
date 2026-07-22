# Long TOP25 NT Runtime Parity — March 2025 — INTERIM STATUS

## Adjudication

**`LONG_MARCH_2025_RUNTIME_PARITY_PARTIAL`.** Layer A is closed: on the matched
population the live NT event loop reproduces the frozen offline pipeline
**exactly** — all 25 features at `0.0` and the model probability at `2.22e-16`.
It is PARTIAL, not PASS, because candidate-population parity is 99.32%, not
exact, and Layer B (Phases 4–5) has still never been run.

| Layer | Status |
|---|---|
| MODEL PARITY STATUS | **PASS** — 25/25 features exact, score exact, 15,131 rows |
| POPULATION PARITY STATUS | **PARTIAL** — 99.32% of offline rows matched |
| TRIGGER-HARNESS STATUS | **NOT RUN** (Layer B still correctly gated) |
| PRODUCTION-THRESHOLD STATUS | **NOT_SELECTED** (unchanged) |

Run: `results/run_manifest_layerA_v2.json`, `results/reconciliation_layerA_v2.json`
(real `BacktestEngine`, 2,023,875 1s + 56,751 1m bars, Feb-01 warmup → Apr-01,
831 s). Tests: 16/16 pass.

## Phase 2 — features: **PASS (25/25)**

| | before | after |
|---|---|---|
| features exact | 12/25 | **25/25** |
| max abs diff, any feature | 8.66 | **0.0** |
| null-mask disagreements | 12 | **0** (36 offline nulls = 36 live nulls) |

## Phase 3 — score: **PASS**

| comparison | max abs diff | tol | status |
|---|---|---|---|
| probability, live joblib vs offline | 2.22e-16 | 1e-10 | PASS |
| probability, live explicit vs offline | 3.33e-16 | 1e-10 | PASS |
| probability, explicit vs joblib | 3.33e-16 | 1e-10 | PASS |
| logit, live vs offline implied | 3.55e-15 | 1e-10 | PASS |

Was `3.16e-02` (FAIL). The scoring path was never at fault — it was
pre-validated at `5.55e-17` — so this is entirely the feature fix landing.

## The defect: the offline replay's "minute" is not a minute

`attach_features_long.py:139` imports `attach_features.minute_bucket_key`
verbatim, deliberately, so the upstream CRIT-1 fix could not drift:

```python
return (bar_ts - 1) // (60 * NS)      # correct for CLOSE-labelled bars
```

The same file's header states its raw 1s bars are **OPEN-labelled** — that is
the entire justification for its change 3. Applied to open-labelled bars the
bucket becomes `(m-60s, m]`: every synthesized minute is shifted **+1 second**
off the true minute, and its rollover fires at the bar `ts == m+1s`, not
`ts == m`. The live engine was driving `PriceLevelTracker` and the RTH
accumulators from the catalog 1m bar — the wrong 60 seconds, one bar early.

**Measured, not inferred.** Offline `rth_vol_cum` reads 1180 at 08:30:05 and
5253 at 08:31:05 on 2025-03-03. Raw 1s volume summed over `(08:29:00, 08:30:00]`
is **1180**; over `(08:29:00, 08:31:00]`, **5253** — exact. The true-minute
reading gives 706 and 5226, which is precisely what the live run produced.

Not a look-ahead: the newest bar folded in (`ts == m`) covers `[m, m+1s)`, and a
snapshot that can see it sits at a snap bar `S >= m` for an observation `O > S`,
so `m + 1s <= O`. Causally implementable live, and now implemented.

It also explains the 12 offline-null rows in `rth_elapsed_seconds`,
`rth_vol_cum` and `opening_range_30m_low_developing_*`: at an observation of
exactly 08:30:00 the rollover (due at 08:30:01) has not run, so RTH has not
opened. Live now reproduces those nulls.

### The hypothesis this replaces was wrong, and cheaply refuted

The previous report named the `update_1m` **inputs** (1s-aggregated OHLC +
`prev_close` vs the catalog 1m bar's own OHLC) as the leading cause of 8 failing
features. Tested before any code changed: over 2025-02-25 → 2025-03-04 the two
agree on **7,259 of 7,260 minutes** (the exception is a minute holding a single
1s bar), and catalog 1s is byte-identical to `data/raw/NQ_v0_1s_2025.parquet`
across 275,446 bars. The values were never the problem — the bucket boundary and
the rollover position were.

The diagnostic that pointed the right way: splitting mismatches by phase within
the minute. `aligned_price_minus_center_*` failed on **88/88 minute-boundary
observations and 0 elsewhere** — a pure timing signature, not an arithmetic one.

## Second convention: two RTH rules

The offline attach's `is_rth` (`CODEX_5_X_run_established_fade.py:146`) ends RTH
at **15:00** Chicago; the study's decision/fill rule is **15:15**. Both now
exist: `common.is_rth_feature_minute` (features) and `common.is_rth_minute_of_day`
(population). Collapsing them leaves `rth_vol_cum` populated for 15 minutes
after the offline reference has gone null.

## What changed

| file | change |
|---|---|
| `common.py` | `minute_bucket_key`, `is_rth_feature_minute` — both documented with the measured proof |
| `long_feature_engine.py` | owns minute-bucket aggregation + rollover; **no 1m update path exists any more** |
| `strategy.py` | `_on_1m` is regime detection only; center ATR pinned to the snap bar |
| `tests/` | +5 convention tests (16/16 pass), mutation-tested |

The 5 new tests were verified non-vacuous: reverting `minute_bucket_key` to the
"sensible" `ts // 60s` fails all three convention tests, including the
behavioural one that reads back the synthesized minute's OHLC membership.

## Phase 1 — population: unchanged at 99.32% (the remaining gap)

Untouched by this fix, and identical before and after — confirming the change is
confined to the feature path.

| metric | value |
|---|---:|
| offline eligible | 15,234 |
| live eligible | 15,576 (+2.25%) |
| exact key matches | **15,131 (99.32%)** |
| offline-only / live-only rows | 103 / 445 |
| offline / live / shared regimes | 146 / 148 / 146 |
| regimes with exact checkpoint-index sets | 71 / 146 |

Displacement of symmetric-difference rows: `>30s` 267, `no counterpart` 124,
`±2–5s` 112, `±6–30s` 45. Live is uniformly *more* permissive (2 extra regimes,
+445 rows), consistent with the SPEC's recorded limitation that the prepared
offline artifact stores only surviving rows, so upstream waterfall stages are
not recoverable offline. **Not yet attributed** — this is the open item.

## Methodological limitations

One month, March 2025 only. Nothing is established about annual behaviour and
nothing about 2026, which was never touched. No economics, no PnL, no threshold.
Layer B has not run, so nothing here supports a deployment claim.

## Audit gate — run, 0 CRITICAL

`lookahead-auditor` re-run after the rewire: **0 CRITICAL / 2 WARNING / 3 NOTE**
(`audit/audit.md`). The `S >= m` non-look-ahead argument was re-derived
independently against the code across gaps, warmup start, missing leading
seconds and session edges, and survived — the live guarantee is actually
`S >= m + 1s`, stronger than claimed.

- WARNING 1, waterfall counters not emit-window gated — **fixed**; the artifact
  was regenerated from the ledger (raw 161,549 → established 54,851 →
  decision_rth 15,576 → eligible 15,576, now comparable to offline's 15,234).
- WARNING 2, `_enter`/`_check_stop` book the snap price and exact stop level
  rather than NT-realized fills — **open and blocking Phase 4**. Inert in every
  run to date (`trigger_threshold=-1.0`, 0 triggers), so no Layer A number is
  affected.
- NOTE 2, a checkpoint due exactly at a regime-flip instant is dropped rather
  than mis-evaluated — undercount, not causality; possible Phase 1 contributor.

Separately: `valid_fill` is hardcoded `True` and `fill_rth` is `= decision_rth`,
so two of six waterfall stages never filter anything and must not be read as
evidence.

## Decision-relevant next step (exactly one)

**Attribute the stream-TERMINATION difference behind Phase 1.** Live and offline
agree exactly on where every candidate stream *starts* (identical first
checkpoint index) and diverge only on where it *ends*, with live always running
longer — 5 regimes supply 382 of the 445 live-only rows, and the 124
`no counterpart` rows are exactly the 2 live-only regimes. The established gate
is therefore reproducing correctly; the open question is narrower than
"attribute the population gap".

Do not open Layer B until that is closed or explicitly accepted, and not before
WARNING 2 is fixed.
