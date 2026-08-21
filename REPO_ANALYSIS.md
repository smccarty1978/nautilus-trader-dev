# Repo-Wide Script Consolidation Analysis

**Repo:** `smccarty1978/nautilus-trader-dev` · **Analyzed:** 1,631 Python files, 374,184 lines **Method:** read-only AST/import fingerprinting + structural clustering. No files modified except this report.

> [!IMPORTANT]
> **PARTIALLY SUPERSEDED — 2026-08-16.**
> **The diagnosis in this report stands and remains the reference for the duplication
> problem** (Clusters C1–C6, the drift measurements, and the "canonical patterns live in
> prose, not importable code" root cause).
>
> **The proposed remedy — a new top-level `common/` package — is SUPERSEDED and must not be
> built.** Subsequent inventory (`BACKTEST_HARNESS_B0_BOUNDARY.md`, verified against code)
> found that production-grade implementations of every concern this report proposed to create
> already exist in **`backtests/nt_runtime/`** and **`utils/runner/`**:
>
> | This report proposed | Already exists as |
> | --- | --- |
> | `common/instruments.py` | `backtests/nt_runtime/engine_builder.py::create_futures_instrument` |
> | `common/engine.py` | `backtests/nt_runtime/engine_builder.py::build_engine` |
> | `common/catalog.py` | `utils/runner/data.py::CausalDataLoader` + `data_plan.resolve_catalog_plan` |
> | `common/reporting.py` | `backtests/nt_runtime/output_manager.py::OutputManager` |
> | `run_backtest.py` (root) | `backtests/run_backtest.py` |
>
> Creating `common/` would add a *second* canonical path beside a runtime that has survived
> six red-team rounds and is inside the collector's sealed AST closure. The governing decision
> is `PROJECT_CONTINUATION_BACKTEST_ANALYSIS_ROADMAP.md` § Architecture principles #1:
> *"Do not introduce a parallel `common/` package unless a concrete constraint requires it."*
>
> Read §5 Track A below as **"promote these concerns to one canonical owner"** — that work is
> done, in `backtests/nt_runtime/`, not in `common/`.

* * *

## 1\. Executive Summary

You are not imagining the token burn — but its root cause is **not** what the raw file counts suggest. The problem is not that you have 1,631 scripts; it is that **your canonical patterns live in documentation prose, not in importable code.** Every time an agent (or you) starts a new study, it re-reads `docs/BACKTEST_EXECUTION.md` and _regenerates_ the same engine-setup, instrument-construction, and catalog-loading code from scratch — because there is no `from common import ...` to call instead.

The single most important finding:

> **The architecture documented in `AGENTS.md` and `docs/` does not exist as code.** `AGENTS.md` specifies a reusable `backtests/engine.py` and `backtests/configs/*.yaml` — **neither file exists.** `docs/BACKTEST_EXECUTION.md` documents a `run_backtest(strategy_class, strategy_config, ...)` function — but it is a _code snippet inside a Markdown file_, not an importable module. Agents follow the docs by copy-pasting the snippet, then editing it inline. That is the token-burn engine.

The quantitative evidence:

| Signal | Count | Why it matters |
| --- | --- | --- |
| Files hand-rolling the `sys.path.insert` + `os.chdir(project_root)` preamble | **471** | Identical 5-line bootstrap re-typed into nearly a third of the repo |
| Files re-implementing `create_instrument()` (the XCME futures `to_dict`/`from_dict` dance) | **28** | One canonical instrument factory, copied 28× |
| Distinct `create_instrument` body hashes among those 28 | **8+** | **Drift** — copies have diverged; a fix to one does not reach the others |
| Files instantiating `BacktestEngine`/`BacktestNode` | **101** (22,216 lines) | Each rebuilds engine config, venue config, logging, catalog load |
| Files hardcoding the catalog path `NQ_v0_2020_2026` | **107** | Config is hardcoded, not surfaced — sweeps require editing code |
| Files importing from _other_ studies (`from studies.X import ...`) | **184** | A fragile cross-study web; renaming one study breaks others |
| Files using the _actual_ shared module `utils/runner/` | **4** | The one real shared module is almost entirely ignored |
| Entry-point scripts (`run_*`/`collect*`/`analyze*`/`train*`) | **500** | The sprawl surface |
| Study directories | **79** (only 61 have `SPEC.md`) | 18 studies are undocumented |

**Headline recommendation:** Do **Track A first, but a narrow version of it.** You do not need a grand config-driven generator. You need to **promote the three already-existing, already-copied skeletons into a single canonical owner** (instrument factory, engine bootstrap, catalog loader) and then add **one** thin `run_backtest.py` CLI that consumes them. _(Superseded detail: this report proposed a new `common/` package for that owner; the canonical owner is in fact the existing `backtests/nt_runtime/` + `utils/runner/`. See the banner above.)_ This absorbs the largest duplication cluster (the 101 backtest files and 28 instrument factories) with the least design risk. Track B (CLAUDE.md rules) is then a _small_ addition that points agents at the new `common/` package — its job is to stop the regeneration habit, and it only works once there is something real to point at.

**Track B alone will fail.** Your CLAUDE.md is already excellent — it has token discipline, audit gates, risk tiers, and a docs index. Adding more prose rules telling agents "reuse the pattern" changes nothing when the pattern is only available as prose to copy. Track B's leverage comes entirely from referencing Track A's importable modules.

* * *

## 2\. Script Inventory

Classification is by static analysis of imports and API usage (a file is BACKTEST if it instantiates an engine and runs a strategy; COLLECTOR if it fetches/persists external data; ANALYSIS if it post-processes results; UTILITY otherwise; MIXED if it spans roles). Treat the per-file labels as directional, not exact — the _cluster_ signal (§3) is the reliable output.

### 2.1 Distribution by class and directory

| Directory | BACKTEST | COLLECTOR | ANALYSIS | MIXED | UTILITY | **Total** | Lines |
| --- | --- | --- | --- | --- | --- | --- | --- |
| studies | 28 | 12 | 212 | 21 | 406 | **679** | 139,470 |
| backtests | 22 | 39 | 187 | 24 | 207 | **479** | 142,539 |
| scratch | 0 | 0 | 69 | 2 | 134 | **205** | 25,053 |
| archive | 11 | 21 | 32 | 9 | 85 | **158** | 44,882 |
| collectors | 7 | 1 | 5 | 2 | 24 | **39** | — |
| scripts | 1 | 1 | 0 | 0 | 7 | **9** | — |
| utils | 0 | 0 | 1 | 2 | 14 | **17** | — |
| features | 0 | 1 | 0 | 0 | 11 | **12** | — |
| tests | 0 | 0 | 0 | 0 | 17 | **17** | — |
| indicators / strategies / models / (root) | 0 | 2 | 1 | 0 | 26 | **30** | — |

> Note: the large UTILITY counts in `studies/` and `backtests/` are mostly _helper modules and per-study libraries_ (feature builders, model trainers, shared per-study `common.py` files), not backtests. The high ANALYSIS counts reflect the heavy post-processing / ML-evaluation character of your studies (sklearn appears in 194 files, lightgbm in 103).

### 2.2 Nautilus component usage (files using each)

`ParquetDataCatalog` 195 · `Bar` 192 · `BacktestEngine` 101 · `Money` 98 · `Strategy` 96 · `Venue` 84 · `TestInstrumentProvider` 61 · `BarType` 58 · `Quantity` 42 · `Databento` 23.

The dominance of `ParquetDataCatalog` (195) + `TestInstrumentProvider` (61) confirms the two hottest boilerplate zones: **catalog loading** and **instrument construction**.

### 2.3 Config surface

What actually varies run-to-run (and should be config): instrument/symbol, year/date-range, policy label (`B0`–`B5`), strategy params (`theta`, `N`), catalog path, output dir. What is currently **hardcoded** in the majority of runners: the catalog path (107 files), the instrument magic dates (`activation_ns`/`expiration_ns`, 55 files), the multiplier/price-increment, and the venue. This is why sweeps require editing source instead of passing flags.

* * *

## 3\. Duplication Clusters

### Cluster C1 — The Backtest Engine Bootstrap _(largest, highest value)_

**Members:** 101 files instantiating `BacktestEngine`/`BacktestNode` (22 in `backtests/`, 28 in `studies/`, plus collectors and archive). Representative: `backtests/run_w4_backtest.py`, `backtests/run_staged_backtest.py`, `backtests/hmm_state_filtered/run_backtest.py`, `backtests/baseline_flip_parity/run_backtest.py`.

**Shared skeleton (~60–90 lines each):**

1.  `sys.path.insert(0, str(project_root)); os.chdir(project_root)` preamble
2.  `PRODUCT_CFG` dict (symbol, multiplier, price\_increment, bar\_type\_1s/1m, instrument\_id, catalog path)
3.  `create_instrument()` → `TestInstrumentProvider.future(...)` → `to_dict` → patch `activation_ns`/`expiration_ns`/`multiplier`/`price_increment` → `FuturesContract.from_dict`
4.  `BacktestEngineConfig` + `LoggingConfig` + venue/account setup (`AccountType`, `OmsType`, `Money`)
5.  `ParquetDataCatalog(path)` → `catalog.bars(...)` with a lead-in buffer (`start - 5 days`)
6.  `engine.run()`, then result export

**Quantification:** ~101 files × ~70 shared lines ≈ **7,000 lines of near-identical engine setup.** Verified drift: the `create_instrument` body has **8+ distinct hashes** across 28 files — `run_staged_backtest.py` and `scripts/run_isolated_sweeps.py` are byte-identical; the `baseline_flip_parity`/`hmm_state_filtered` family shares a different hash; several studies have their own variants. **This is a live bug-broadcast risk.**

### Cluster C2 — The Instrument Factory

**Members:** 28 files with `create_instrument`, 57 with the `TestInstrumentProvider.future` dance, 55 with the 2019 `activation_ns` magic date. **Skeleton:** the `to_dict`→patch→`from_dict` futures-contract construction. **This should be one function** parameterized by symbol. It is the single most-copied _correct_ block and the most dangerous to let drift (wrong `activation_ns` = silent look-ahead).

### Cluster C3 — The Catalog Loader

**Members:** 195 files using `ParquetDataCatalog`; 107 hardcoding `NQ_v0_2020_2026`. **Skeleton:** open catalog → `catalog.bars(bar_type, start, end)` → apply lead-in → optionally `ts_init_delta` wrangle. A shared loader already exists — `utils/runner/data.py::CausalDataLoader` — but is used by only **4 files**. The other ~191 re-open and re-wrangle the catalog inline.

### Cluster C4 — The Path Bootstrap

**Members:** 471 files with `sys.path.insert` + `os.chdir`. **Skeleton:** 4–6 lines making the repo root importable and CWD-stable. This is pure mechanical noise — a `common/bootstrap.py` (or a proper `pyproject.toml` install / `conftest.py` path fix) eliminates all of it.

### Cluster C5 — Paired-Study Copy-Paste

**Members:** `studies/f2_confirmed_exit_management/` ↔ `studies/all_flips_exit_management/` (identical `build_phase1_atlas.py`, `build_phase3_w0_model.py`); `studies/pre_flip_signal_reliability/` ↔ `..._top103/` (identical `export_summaries.py`); `backtests/studies/regime_dna_knn/` duplicated into its **own `results/`** (`early_health_filter.py`, `regime_pullback_lifecycle.py`, etc. — code committed into results dirs). **Skeleton:** whole analysis modules copied between a parent study and a variant. ~3,400 redundant lines in exact-duplicate form alone.

### Cluster C6 — Cross-Study Import Web

**Members:** 184 files doing `from studies.X import ...` or `sys.path.insert(<another study>)`. **This is the hidden fragility.** Studies reach into each other's `implementation/` folders (e.g. `codex_5_w4_fade_confirmation_clock/run_study.py` imports `CODEX_5_X_common` and `CODEX_5_X_run_established_fade` from a _different_ study via `sys.path.insert`). Renaming or accepting one study silently breaks its dependents. These shared helpers (`CODEX_5_X_common`, `early_health_filter`, `progressive_separability` — the latter two imported by 80 and 73 files respectively) are de-facto libraries that should be promoted to `common/`.

### Canonical patterns (what your "framework" actually is)

-   **Backtest:** bootstrap → `PRODUCT_CFG` → `create_instrument` → engine+venue config → `CausalDataLoader`\-style catalog load with lead-in → `add_strategy(ImportableStrategyConfig)` → `run()` → export trades/equity/metrics.
-   **Collector:** Databento historical fetch → wrangle (`ts_init_delta` for 1m, none for 1s) → `ParquetDataCatalog.write_data` → manifest.
-   **Analysis:** load NT fills/positions → pandas/numpy metrics (win-rate, MFE/MAE, Sharpe, drawdown) → sklearn/lightgbm modeling → parquet/csv export. Tearsheets via `TearsheetConfig` where used.

* * *

## 4\. Agent Setup Gaps

Your `CLAUDE.md` (48 lines) + `AGENTS.md` (365 lines) are genuinely strong: core invariants, token discipline, split audit gate, bounded re-audits, commit protocol, risk tiers, subagent output caps, standing authorization. The gaps are **not** about process — they are about the _missing code layer_:

1.  **The documented architecture is aspirational, not real.** `AGENTS.md` § DIRECTORY STRUCTURE promises `backtests/engine.py` ("Reusable backtest runner") and `backtests/configs/{strategy}_{version}.yaml`. **Neither exists.** `docs/BACKTEST_EXECUTION.md` § "Standard Backtest Runner" gives a `run_backtest(...)` function **as a Markdown code block.** An agent following the docs has no choice but to copy the snippet and edit it — there is nothing to `import`. _This is the #1 gap and the direct cause of Cluster C1._
2.  **No rule points agents at the one shared module that does exist.** `utils/runner/` (`CausalDataLoader`, `DailyStateCheckpointer`, etc.) is used by 4 files and mentioned nowhere in CLAUDE.md/AGENTS.md. Agents don't know it exists, so they re-open catalogs inline.
3.  **No "new study" decision tree that routes to a template.** CLAUDE.md has risk _tiers_ (1/2/3) but no "when starting a new study, scaffold from X" rule. So each new study re-derives the bootstrap, instrument factory, and loader.
4.  **The cross-study import web is ungoverned.** Nothing says "shared helpers live in `common/`, never `sys.path.insert` into a sibling study." Result: 184 cross-study imports and de-facto libraries (`early_health_filter`, `progressive_separability`) buried inside individual studies.
5.  **Stale/contradicted items:** the `AGENTS.md` directory tree (engine.py, configs/, `studies/{name}/collect.py + analyze.py`) describes a layout the repo does not follow (studies use `run_*.py`, not `collect.py`/`analyze.py`; 18/79 studies lack the mandated `SPEC.md`). Docs that describe a fiction train agents to improvise.

* * *

## 5\. Consolidation Plan

### Track A — Shared `common/` package + one thin runner _(do this first)_

> [!WARNING]
> **SUPERSEDED — do not create `common/`.** The layout sketched below was written before
> `backtests/nt_runtime/` was inventoried. Every box in the tree already has a canonical owner
> (see the banner at the top of this document). The *intent* of Track A — one implementation
> per concern, consumed by a thin CLI — is being delivered as
> `backtests/nt_runtime/modes/backtest.py` + `backtests/run_backtest.py`.
> Treat the tree below as a statement of required capabilities, not a target directory layout.

Do **not** build a grand config-driven generator yet. Promote the three already-proven skeletons into a real package, then add one CLI.

```
common/
├── __init__.py
├── bootstrap.py        # the 471× path/CWD setup, as importable setup_repo_root()
├── instruments.py      # create_future(symbol) — absorbs Cluster C2 (28 copies)
├── catalog.py          # load_bars(symbol, bar_type, start, end, lead_in_days=5)
│                       #   → thin wrapper over utils/runner/data.py::CausalDataLoader
├── engine.py           # build_engine(venue_cfg, log_level) → configured BacktestEngine
│                       #   make docs/BACKTEST_EXECUTION.md's run_backtest() REAL here
└── reporting.py        # export_trades/equity/metrics/tearsheet helpers
run_backtest.py         # CLI: --symbol --year --policy --strategy --param k=v ...
```

-   `common/instruments.py` and `common/engine.py` are near-mechanical extractions of Clusters C1/C2 — low risk, immediate payoff.
-   `run_backtest.py` is a _thin_ CLI over `common/`, not a new framework. It absorbs the most-duplicated cluster (C1) by letting the 101 engine files become `--strategy X --year Y` invocations.

**Absorption estimate:** Clusters C1+C2+C3+C4 cover roughly **101 engine files + 28 instrument factories + 191 inline catalog loads + 471 bootstraps.** Realistically, **~60–70% of the `backtests/` and engine-instantiating `studies/` scripts** could be expressed as `common/` imports + a config/CLI call. The genuinely unique scripts that should **stay standalone**: the ML training pipelines (sklearn/lightgbm feature engineering is study-specific), the causal/matching diagnostics (matched-donor, permutation controls — these are the ones your pre-execution audit gate rightly flags), and one-off collectors.

### Track B — CLAUDE.md additions _(small, and only after Track A exists)_

Add a short block. Its power comes from referencing real modules, not from more prose:

```markdown
## New Study / Backtest — SCAFFOLD, DON'T REGENERATE
- NEVER re-type engine setup, instrument construction, catalog loading, or the
  sys.path/os.chdir preamble. Import them:
    from backtests.nt_runtime.engine_builder import build_engine, create_futures_instrument
    from backtests.nt_runtime.data_plan import resolve_catalog_plan   # generic
    from backtests.nt_runtime.data_plan import resolve_data_plan      # study-bound + OOS gates
    from utils.runner.data import CausalDataLoader
    from utils.causal_registration import add_bars_causal_order
- New backtest run = `python backtests/run_backtest.py --strategy <name> --param k=v`,
  NOT a new run_*.py. Only create a new script if the CLI cannot express it.
- Shared helpers go in backtests/nt_runtime/, utils/runner/, or features/ for registered
  features. NEVER sys.path.insert into a sibling study — promote the helper instead.
- New study dir: studies/<name>/ scaffolded by scripts/create_study.py. See docs/TEMPLATES.md.
```

_(This block has been delivered in `CLAUDE.md` § "BACKTEST / COLLECT — IMPORT, DON'T REGENERATE",
pointing at the real `nt_runtime` modules rather than the superseded `common/` package.)_

Plus one line in `AGENTS.md` correcting the directory tree to match reality (or pointing to `common/`). Keep it under ~15 lines total — your context budget is already a stated concern.

### Recommendation

**Do Track A (narrow) + the small Track B pointer, in that order.** Track A removes the duplication; Track B redirects the agent habit. The token-savings-to-effort ratio is highest for C1+C2+C4 (mechanical extraction, ~9,000+ redundant lines, eliminates the per-session regeneration of engine/instrument/bootstrap code). Defer any larger config-driven generator until `common/` has stabilized and you can see which studies genuinely resist the CLI — those are your real edge cases, and they're cheaper to identify after the mechanical 70% is absorbed.

**Sequenced next steps:**

1.  ~~Create `common/`~~ **SUPERSEDED** — the concerns already live in `backtests/nt_runtime/` and `utils/runner/`. Extend those instead; see `BACKTEST_HARNESS_B0_BOUNDARY.md` §1.
2.  Prove the canonical path against the two frozen legacy fixtures (`run_staged_backtest.py`, `run_w4_backtest.py`) by golden equivalence, rather than by refactoring them.
3.  Add the Track B block to CLAUDE.md. **(done)**
4.  Promote `early_health_filter` and `progressive_separability` (80 and 73 importers) out of their host studies into a shared location to start unwinding the cross-study web. **Still open — not part of the backtest-harness scope.**
5.  Optionally delete `scratch/` (25K lines) and prune `archive/` (45K lines) from the active tree — they're 19% of the repo and dilute every search an agent runs.

* * *

## 6\. Appendix — Method & Per-Cluster Evidence

**Method.** Every `.py` file (excluding `.git`, `__pycache__`) was parsed with `ast`. For each: top-level statement signature, import set, Nautilus-component usage (regex over a fixed component vocabulary), normalized code hash (comments/strings/numbers/whitespace stripped), line count, and a rule-based class. Clusters were derived three ways: exact normalized-hash duplicates, shared import backbone, and shared AST top-level signature. Drift was measured by hashing the 12 lines following each `def create_instrument`.

**Key cluster evidence (verbatim verification):**

-   `backtests/run_w4_backtest.py` and `backtests/run_staged_backtest.py` share a ~45-line `PRODUCT_CFG` + `create_instrument` block that is character-identical except for formatting; both hardcode `NQ_v0_2020_2026`, multiplier `20`, price increment `0.25`, and the 2019→2027 activation/expiration window.
-   `create_instrument` body hashes: `run_staged_backtest.py` ≡ `scripts/run_isolated_sweeps.py`; `baseline_flip_parity/run_backtest.py` ≡ `hmm_state_filtered/run_backtest.py` ≡ `hmm_state_filtered/run_backtest_p1.py`; ≥6 other distinct variants across studies/collectors.
-   `docs/BACKTEST_EXECUTION.md` line 51 "Standard Backtest Runner" defines `run_backtest(strategy_class, strategy_config, data_catalog, venue_config, start_time, end_time, output_dir)` — a Markdown snippet with no corresponding importable file.
-   `utils/runner/data.py::CausalDataLoader.load_bars(catalog_path, bar_type, start, end)` exists and is correct, but only 4 files import `utils.runner`.
-   `studies/codex_5_w4_fade_confirmation_clock/run_study.py` line ~28 does `sys.path.insert(0, str(REPAIR))` then `from CODEX_5_X_common import RAW_1S, sha256_file` — a canonical example of the cross-study import web (Cluster C6).

**Caveats.** Per-file class labels are heuristic (a study's `run_*.py` that both backtests and analyzes is labeled MIXED). Line-level boilerplate percentages are estimates from cluster membership, not per-file diffs. The exact-duplicate line counts exclude the 81 trivial empty `__init__.py` files. All cluster _membership_ and _drift_ claims are verified from file contents; all _percentage_ claims are directional estimates.

_Report generated by static analysis. Source data: `records.json` (per-file fingerprints)._