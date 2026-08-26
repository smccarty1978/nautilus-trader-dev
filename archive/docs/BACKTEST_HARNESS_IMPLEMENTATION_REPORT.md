<!-- DOC-STATUS-BANNER -->
> **[HISTORICAL]**
>
> A point-in-time record of the build of the backtest harness. It is not a description of the current system
> and not a source of instructions.
>
> Current authority: **`docs/RESEARCH_WORKFLOW.md`**. Classification: `docs/DOCUMENT_MAP.md`.

# Backtest Harness — Implementation Report

**Date:** 2026-08-16 · **Base commit:** `97b97db` · **Branch:** `study/Codex_clean_maturity_flip_rolling_5m_productivity`
**Nothing was committed or pushed.** The working tree is left clean and reviewable.

## FINAL STATUS: `READY_FOR_INDEPENDENT_RED_TEAM_WITH_LIMITATIONS`

Both legacy fixtures now run unmodified, both have valid frozen baselines with complete source
provenance, and both pass golden equivalence through the new harness. The audit-parser and
agent-definition defects are fixed and covered by tests.

The one limitation is expected and by design: the collector's pre-execution seal is **stale**, because
five files inside its closure changed. That is recorded as
**`REQUIRES_INDEPENDENT_RED_TEAM_RESEAL`** — not as an unexplained blocker. No audit was
self-certified, no `CLEAR` was authored by me, and no claim is made that the seal is restored.

| Gate | Result |
|---|---|
| Fixture 1 (ScoreFanning) runs unmodified | ✅ fixed — 3 NT-compatibility defects repaired |
| Fixture 2 (W4) runs unmodified | ✅ unchanged |
| Baseline capture | ✅ **`VALID`** — both fixtures `SUCCESS` |
| Source-closure provenance | ✅ complete, mechanically derived, provenance-tagged |
| Golden equivalence — fixture 1 | ✅ **PASS** |
| Golden equivalence — fixture 2 | ✅ **PASS** |
| Audit parser false positives | ✅ fixed + 40 tests |
| Independent audit ingestion path | ✅ implemented + tests |
| `contract-checker` read-only/write contradiction | ✅ resolved, synced to 3 toolchains |
| Collector seal | ⚠️ `REQUIRES_INDEPENDENT_RED_TEAM_RESEAL` |

---

## 1. Repairs made in this pass

### 1.1 ScoreFanning — three NT-compatibility defects (not one)

The first pass reported only the mutable-default error, because that error aborted the module at
import and masked the two behind it. Each was fixed with the framework-correct mechanism; **no
semantics, thresholds, output paths, or evaluator behaviour were changed.**

| # | Defect | Repair |
|---|---|---|
| 1 | `ScoreFanningConfig.policies` used a non-empty mutable list as a msgspec field default → `TypeError` at class creation | `msgspec.field(default_factory=lambda: [...])`, values byte-identical to the original literal |
| 2 | `__init__` called `self.cache.instrument(...)` / `self.cache.bar_type(...)`; `self.cache` is `None` until the strategy is registered with a trader (which happens after `__init__`) → `AttributeError: 'NoneType' object has no attribute 'instrument'` | Parse identifiers from the declared config strings: `InstrumentId.from_str` / `BarType.from_str`. Same identifiers, no dependence on registration order. This is the pattern the sealed `flip_prediction_collector` already uses. |
| 3 | `on_start` called `self.request_data_subscription(...)`, which does not exist on `nautilus_trader.trading.strategy.Strategy` in 1.230.0 | `self.subscribe_bars(...)`, again matching the working collector |

**Evidence the semantics are unchanged.** The unmodified legacy command now runs and reports
`Saved 20 trades for policy R2.5` — the same trade count as the pre-invalidation run — and the
resulting `results_R2.5.parquet` normalizes to `5fc8096451508481`, **identical** to the hash of the
artifact captured before any of these fixes.

Regression tests (`scripts/tests/test_nt_runner_backtest.py`): import/instantiate succeeds; default
policies equal the legacy values including order and both thresholds (0.62 / 0.50), asserted against a
copy of the list held independently in the test file so a value change would fail; defaults are not
shared between instances; `checkpoint_dir` default unchanged; explicit `policies=` still overrides.

### 1.2 Baseline dependency provenance — closure resolver rebuilt

The three-file W4 closure was accurate but **unproven**, and the resolver was demonstrably incomplete:
fixture 1's closure omitted `utils/__init__.py`, which Python executes on `from utils.runner...`.

`resolve_repo_local_closure_detailed()` now walks:

| Discovery reason | What it captures |
|---|---|
| `entrypoint` | the fixture script itself |
| `static_import` | `import x`, `from x import y` (including `y` as a submodule), relative imports |
| `package_init` | **every ancestor package `__init__.py`** on the path to an imported module |
| `dynamic_string_literal` | dotted module paths appearing as string constants — registry `module_path` values, study `strategy_class`, `importlib.import_module("…")` — kept only if they resolve to a repo-local file |

Every closure entry carries its discovery reason in the manifest, so completeness is auditable rather
than asserted. This is a structural rule, **not a curated filename list**.

Tests: ancestor package inits; three-level transitive chains; `from pkg import mod`; dynamically
resolved registered strategy modules; dotted strings that resolve to nothing must not inflate the
closure; and a regression test pinning `utils/__init__.py` into fixture 1's closure.

### 1.3 Audit infrastructure

**Parser false positives fixed.** A finding is now counted only when a line is a heading/bullet of the
form `SEVERITY: <title>` with a mandatory colon and a non-empty, non-count title. `## Critical
findings` (no colon) and `- Critical: 0` (numeric title) are no longer findings.

A second false positive surfaced while testing and was fixed: `- **Critical:** 0` puts the colon
*inside* the emphasis, so the captured title was `** 0` and escaped the count check. Emphasis is now
stripped from both ends. **This one was a real regression I introduced and then caught** — it broke
10 tests in `test_round2_invariants.py`, which parse the real `pass_10.md`; all are green again.

**Independent-audit ingestion path added** — `run_preexec_audits.py --ingest <report.md> --author <id>`.
It exists so an auditor that cannot write into the repo can still supply evidence without anyone
authoring a verdict on its behalf. It fails closed on: non-Markdown source (a status JSON can never be
supplied — status is always re-derived), a source already inside `audit/` (self-asserted), missing or
malformed `AUDIT_SUMMARY_V2`, summary-vs-heading inconsistency, absent or mismatched `study` binding,
absent or stale `audited_execution_composite_sha256`, and overwriting existing pass evidence.

An ordering bug found by these tests: the report was originally filed **before** heading validation
completed, leaving a rejected artifact behind. Validation now runs entirely on the source before any
write, and the ingestion tests operate on a scratch copy of the study so they cannot touch real
evidence. (One `contract_pass_99.md` written into the real study by that bug was removed.)

**Agent contradiction resolved.** `.claude/agents/contract-checker.md` declared `tools: [Read, Grep,
Glob]` and "You are read-only. Do not modify files," while instructing the agent to *write*
`audit/contract_status.json`. It now has `Write`, scoped explicitly to its own audit artifacts under
`<study_dir>/audit/` and nothing else — matching `lookahead-auditor`, which already had `Write` for
the same reason. It is told that if it cannot write, it must **not** ask for transcription, and must
instead route through the ingestion path. Propagated to `.codex/` and `.agents/agents_staging/` via
`scripts/sync_agents.py`.

**Pass 11 contract evidence was not created or backfilled by me.**

---

## 2. Valid baseline identity and closure hashes

Authoritative capture: **`backtests/fixtures/baseline_capture_20260816_152758/`** — status **`VALID`**
Capture script SHA-256 `5916e60ac7fb9454…` (verified unchanged across the run) · git `97b97dbab60d`

### Fixture 1 — ScoreFanning, 2023-03-03 — `SUCCESS`, `baseline_valid: true`

`python backtests/run_staged_backtest.py --start-date 2023-03-03 --end-date 2023-03-03`

Closure: **8 files** (1 entrypoint, 6 static imports, 1 package init) — stable across the run.

```
2ac163029d7b  backtests/run_staged_backtest.py      (entrypoint)
412bfda3b12b  strategies/score_fanning_strategy.py  (static_import)
f5bfd4d28895  utils/__init__.py                     (package_init)   <- previously missing
9e24e74446f7  utils/runner/checkpoint.py            (static_import)
c2aa3d77523c  utils/runner/data.py                  (static_import)
8b23d34fd157  utils/runner/fanning.py               (static_import)
9bc8b0610280  utils/runner/progress.py              (static_import)
eb52847d1b36  utils/runner/registry.py              (static_import)
```

| Target | Status | Identity |
|---|---|---|
| `results_R2.5.parquet` | `produced_by_current_run` | 20 rows · `5fc8096451508481` |
| `results_R5.parquet` | `expected_absent_verified` | — |
| `resume_manifest.json` | `produced_by_current_run` | — |

Resolved config materialised from the real config class: 21 fields.
R5's absence is code-grounded: the strategy emits a constant `dummy_score = 0.55`, below R5's 0.62
threshold, so its evaluator opens no trades and the runner's `if trades_list:` is False.

### Fixture 2 — W4 Exit B1, full-year 2023 — `SUCCESS`, `baseline_valid: true`

`python backtests/run_w4_backtest.py --year 2023 --policy B1 --theta 0.62 --N 10`

Closure: **3 files** (1 entrypoint, 2 static imports) — stable across the run. Now *proven* complete:
`baseline_flip_parity/strategy.py` imports only `nautilus_trader` and stdlib, and none of
`backtests/`, `strategies/`, `backtests/baseline_flip_parity/` contains an `__init__.py`, which a test
asserts explicitly rather than assuming.

```
9d76df8bed2b  backtests/run_w4_backtest.py                 (entrypoint)
1fa44a0a4f01  strategies/w4_exit_strategy.py               (static_import)
916f6d66e25a  backtests/baseline_flip_parity/strategy.py   (static_import)
```

| Target | Status | Identity |
|---|---|---|
| `trades.parquet` | `produced_by_current_run` | 18,372 rows · `4db473610703d8f3` |
| `strategy_trades.parquet` | `produced_by_current_run` | 18,372 rows · `3b4840afb506815c` |
| `w4_parity_2023_B1.parquet` | `expected_absent_verified` | — |

Resolved config: 38 fields (`entry_qty=1`, `year=2023`, `policy=B1`).
External input `weakness_checkpoint_predictions.parquet` sha `d66a761bd5dbc2c2…`, 664,162 rows for 2023.
Catalog: 12,395,770 1s bars · 358,816 1m bars with first/last `ts_event`+`ts_init`.

Every declared target was preserved before the run and restored after; 12 `w4_parity_20{25,26}_B*.parquet`
files were classified `preexisting_stale_unmanaged`, hashed, left in place, never attributed.

---

## 3. Golden equivalence results

Both replay real market data through the new harness and compare **normalized content hashes** —
identical row counts, identical column sets, identical content, **no columns excluded**.

| Fixture | Command | Result |
|---|---|---|
| 1 — ScoreFanning (`virtual`) | `RUN_GOLDEN_EQUIVALENCE=1 pytest …::test_score_fanning_harness_matches_frozen_baseline` | ✅ **PASSED** |
| 2 — W4 (`simulated_orders`) | `RUN_GOLDEN_EQUIVALENCE=1 pytest …::test_w4_harness_matches_frozen_baseline` | ✅ **PASSED** in 330.28s |

Fixture 1 additionally asserts the other half of the virtual contract: no `results_R5` artifact is
produced, `R5` appears in `evaluator_tables_empty`, and the NT positions report is empty — matching the
baseline's `expected_absent_verified` classification for R5.

Fixture 2 compares both `trades.parquet` and `strategy_trades.parquet`.

**On pinning `trader_id`.** The first W4 attempt failed on content hash. First-divergence localization
(per `CLAUDE.md`'s rule, before any broad search) showed 3 of 21 columns differing across all 18,372
rows — `trader_id`, `opening_order_id`, `closing_order_id` — while every economic field (side,
quantity, `ts_opened`, `ts_closed`, `avg_px_open`, `avg_px_close`, `realized_pnl`, `realized_return`,
commissions, duration) matched exactly. NT composes client order IDs as
`O-<date>-<time>-<trader-suffix>-<seq>`, so the two order-ID columns differed *solely* because the
trader id did. Pinning `trader_id` lets the comparison **cover** the order-ID columns instead of
excluding them, which is stronger than the B0 §5 allowance to exclude `trader_id` from comparison
hashes. A reviewer should still confirm this is not masking anything: the localization output is
reproducible by removing the `trader_id` argument from the test.

---

## 4. Test results

```
pytest scripts/tests/{test_capture_baseline_fixtures, test_nt_runner_backtest,
                      test_audit_report_ingestion, test_round2_invariants,
                      test_nt_runner_collect, test_spec_fidelity_and_oos_lock,
                      test_audit_seal_guard}.py
→ 179 passed, 2 failed, 2 skipped
```

| Suite | Result |
|---|---|
| `test_capture_baseline_fixtures.py` | 48 passed — statuses, preservation/restoration, quarantine, closure completeness, gates |
| `test_nt_runner_backtest.py` | 48 passed, 2 skipped (the golden tests, run separately above) |
| `test_audit_report_ingestion.py` | 40 passed — parser zero/one/mixed severity + ingestion rejection matrix |
| `test_round2_invariants.py` | 18 passed — restored after my emphasis-stripping regression |
| the 2 failures | both `PREEXEC_AUDIT_STALE`, same root cause (§5) |

Collector preflight: **`BLOCKED`**, gate `CAUSAL_INVARIANTS` — **264 passed, 1 failed**, the single
failure being the seal-guard test detecting the expected staleness.

---

## 5. Collector seal — `REQUIRES_INDEPENDENT_RED_TEAM_RESEAL`

Five of the 75 sealed entries have drifted. The other 70 verify clean.

| Drifted | Why |
|---|---|
| `backtests/nt_runtime/data_plan.py` | `resolve_catalog_plan` extraction |
| `backtests/nt_runtime/engine_builder.py` | `ExecutionMode` contract |
| `backtests/nt_runtime/strategy_binding.py` | backtest registrations + `allow_unregistered` |
| `scripts/run_preexec_audits.py` | audit parser fix + ingestion path |
| `audit/status.json` | re-derived causal status, now pass 11 |

`strategies/score_fanning_strategy.py` is **not** in the collector closure, so the ScoreFanning repairs
do not affect the seal.

Chain state — what exists and what does not:

| Step | State |
|---|---|
| Causal audit pass 11 | `CLEAR` (0 critical, 0 warning, 2 notes). `lookahead-auditor` authored `audit/pass_11.md`; `audit/status.json` was **re-derived by the parser**, not written by me. |
| Contract audit pass 11 | **Does not exist.** Not created, not backfilled. |
| Seal | Not regenerated. `preexec_audit_seal.py` refuses: *"Execution code modified after Contract Audit! Current `2859b421…`, Contract audit reviewed `f01abb54…`"* |
| Bounded smoke | Not run — collect mode verifies the seal before executing |
| Smoke validation | Not run |

**The collector is not runnable until resealed.** That is the cause of both failing tests.

### Remaining independent Red-Team actions

1. **Independent causal audit** — re-audit the current tree; `pass_11.md` exists but was authored before
   `run_preexec_audits.py` changed, so a fresh pass against the current composite is the clean path.
2. **Independent contract audit** — author `audit/contract_pass_<NN>.md` with an `AUDIT_SUMMARY_V2`
   block carrying `study` and `audited_execution_composite_sha256`.
3. **Status ingestion** — either the agent writes directly (it now has `Write`), or:
   ```
   python scripts/run_preexec_audits.py --study studies/Gemini_clean_maturity_flip_rolling_5m_productivity \
       --pass-num <NN> --type contract --ingest <report.md> --author "<auditor>"
   ```
4. **Seal** — `python scripts/preexec_audit_seal.py --study <study>`
5. **Bounded smoke** — 1-day sealed collect run
6. **Smoke validation** — `python scripts/validate_smoke.py`, then re-run preflight to `CLEAR`

### Also worth the Red Team's attention

- The `dynamic_string_literal` closure rule is deliberately over-inclusive (any dotted string that
  resolves to a repo file is captured). Over-inclusion is safe for provenance but worth confirming it
  does not pull in unrelated files for other entrypoints.
- The `trader_id` pinning argument in §3.
- `ExecutionMode.run_window_mode` / `warmup_days` / `warmup_dispatched` are declared and recorded but
  not yet consumed by `build_engine`/`collect.py` — noted by the causal auditor as a non-blocking note.

---

## 6. Out of scope — untouched, as instructed

- **Analysis A-track (A0–A5)** — not started.
- **Bulk migration** — zero of the 101 engine-instantiating scripts migrated. Both legacy entrypoints
  are byte-identical to `97b97db`; they were executed, never edited.
- **Collector redesign** — no collector code touched. `flip_prediction_collector.py`, the feature
  trackers, `research/engines/*` and `output_manager.py` unchanged.
- **A `common/` package** — not created.
- **Broad repository cleanup** — no documents archived or deleted.
- **Commits/pushes** — none.
