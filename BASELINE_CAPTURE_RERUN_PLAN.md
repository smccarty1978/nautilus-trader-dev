# Baseline Capture Rerun Protocol & Plan (v5.1)

**Status:** Plan Frozen (v5.1 — Enhanced Expected-Absence Handling — Do Not Execute Yet)  
**Objective:** Standardize an immutable baseline capture protocol for legacy backtest fixtures with explicit target output status classification, pre-run quarantine/preservation procedures, and rigorous expected-absence verification.

---

## 1. Output Artifact Status Classification Schema

To prevent false attribution of stale pre-existing files or ambiguous absence reporting, every output target path is classified under one of four explicit statuses:

| Status Code | Definition & Criteria |
|---|---|
| **`produced_by_current_run`** | The file was created or updated freshly during the current fixture execution (verifiable by file creation/modification timestamp and post-run hash comparison). |
| **`expected_absent_verified`** | The target path was verified clean (or safely quarantined) prior to execution, the fixture completed successfully, and no file was generated, proving the expected zero-output contract. |
| **`expected_absent_unverified_due_to_preexisting_target`** | A pre-existing file was present at the target path prior to execution, preventing fresh zero-output verification without quarantine. |
| **`preexisting_stale_unmanaged`** | A pre-existing file found at a target path that is not produced by the current run configuration (e.g. leftover side-effect files from previous runs). Must be preserved and excluded from current run attribution. |

---

## 2. Expected-Absence Protocols for Specific Fixture Targets

### A. ScoreFanning Evaluator Policy R5 (`results_R5.parquet`)
In `run_staged_backtest.py:146-167`, trade output files are saved conditionally:
```python
for evalr in strategy.evaluators:
    trades_list = evalr.trade_history + evalr.active_trades
    if trades_list:
        df = pd.DataFrame(...)
        df.to_parquet(checkpoint_path / f"results_{evalr.name}.parquet")
```

1. **Pre-Run Preservation & Quarantine Procedure:**
   - If `results_R5.parquet` exists prior to execution, it is backed up into `preserved_preexisting/` and moved out of `backtests/results/checkpoints/`.
   - **Rule:** The capture framework CANNOT report R5 as `expected_absent_verified` if a pre-existing file remained in place during execution.
   - If temporary pre-run move/quarantine is authorized: the target directory is clean before running, and if no `results_R5.parquet` is created, the status is logged as `expected_absent_verified`.
   - If pre-run move/quarantine is NOT authorized: the pre-existing file is copied to `preserved_preexisting/` but left in place, and R5 absence is logged as `expected_absent_unverified_due_to_preexisting_target`.

### B. W4 Exit Parity Log (`w4_parity_2023_B1.parquet`)
In `strategies/w4_exit_strategy.py:262-269`:
```python
def on_stop(self):
    if self.parity_logs:
        df_p = pd.DataFrame(self.parity_logs)
        out_p = PROJECT_ROOT / f"backtests/results/w4_parity_{self._cfg.year}_{self._cfg.policy}.parquet"
        df_p.to_parquet(out_p, index=False)
```

1. **The condition is `parity_logs`, not the year.**
   The write is gated on `if self.parity_logs:` — a runtime-populated list. `parity_logs` gains a row
   in `_process_5s_checkpoint` **only** when `self._pred_dict.get((direction, flip_ts, ts))` returns a
   match (`strategies/w4_exit_strategy.py:144-167`; `pred_data is None` returns early). The year is
   merely the filter applied when `_pred_dict` is loaded in `on_start`. Therefore:
   - **Absence is a property of the executed run, never a property of `--year 2023`.**
     A capture MUST NOT pre-declare this file absent, and MUST NOT record a year-derived status.
   - There is no `expected_absent_for_2023` status. That label is **retired**; it was not one of the
     four statuses defined in §1 and it encoded a year-based inference the code does not support.

2. **Permitted classifications for this target** — only the four statuses in §1 may be used:
   - File produced by the run → `produced_by_current_run`.
   - Target verified clean (or quarantined) before the run, run completed, no file created →
     `expected_absent_verified`. The manifest records this as *observed*, with
     `absence_cause: "parity_logs_empty_at_on_stop"` as an interpretation, not as a precondition.
   - A pre-existing file remained in place during execution, so fresh absence could not be proven →
     `expected_absent_unverified_due_to_preexisting_target`.
   - A file exists at a target-shaped path that this run configuration does not produce (e.g.
     `w4_parity_2025_B1.parquet` during a 2023 capture) → `preexisting_stale_unmanaged`. Preserved,
     hashed, left in place, and **never** attributed to the current run.

3. **Primary output evidence** for Fixture 2 remains `trades.parquet` (closed positions) and
   `strategy_trades.parquet` (blended strategy trade log). The parity log is supporting evidence
   whose presence or absence is recorded as observed.

---

## 3. Worktree Gates, Allowlist & Untracked File Archival

### A. Obsolete Scratch Scripts — ARCHIVED
> [!CAUTION]
> **RETIRED:** `scratch/run_baseline_capture.py` is retired and marked **OBSOLETE**. It must never be executed.
> It produced the captures now marked `INVALIDATED` in `backtests/fixtures/baseline_fixtures.json`.

**Archival performed (2026-08-16).** The retired scratch scripts blocked capture under the strict
untracked-`.py` gate. Rather than broadening the allowlist or deleting evidence, their content was
preserved verbatim under a non-executable extension:

```text
backtests/fixtures/forensics/retired_scratch/
├── FORENSIC_MANIFEST.json          # original path, SHA-256, size, mtime for each archived file
├── run_baseline_capture.py.retired
└── inspect_baseline_inputs.py.retired
```

Rules: content is byte-identical to the originals and the SHA-256 of each is recorded in
`FORENSIC_MANIFEST.json`. The `.retired` suffix keeps them out of the untracked-`.py` gate and out of
any import path. They are evidence, not code — **never** restore them to `.py` and never execute them.

### B. Worktree Gate Enforcement
1. `git diff --exit-code` (0 uncommitted working tree modifications).
2. `git diff --cached --exit-code` (0 staged index modifications).
3. `git status --porcelain` scanning for untracked `.py` files.

Gates 1 and 2 are **advisory** for this capture and are recorded in the manifest as
`worktree_clean: true|false` with the exact file list, because the capture protocol itself is
delivered as tracked-file modifications.

**Gate 3 is blocking, and scoped to the import closure.** A static allowlist was rejected: it
requires maintenance, and it answers the wrong question. What matters is not whether a file is
*named* in a list, but whether it can change what the legacy entrypoint executes. The gate
therefore blocks an untracked `.py` if and only if it lies inside the resolved repo-local import
closure of a selected fixture.

This is strictly stronger than an allowlist in the case that actually matters. The closure is
resolved by mapping imported module names onto the filesystem, so a rogue file that *shadows* an
imported module (e.g. a stray `pandas.py` at repo root) resolves **into** the closure and is
blocked. Conversely, new harness code that no fixture imports — `backtests/run_backtest.py`,
`backtests/nt_runtime/modes/backtest.py` — provably cannot affect the replay, and is recorded under
`untracked_py_outside_closure` rather than blocking the capture.

**Always-allowed (the capture tooling itself, which is necessarily untracked at capture time):**
- `scripts/capture_baseline_fixtures.py`
- `scripts/tests/test_capture_baseline_fixtures.py`

Untracked non-`.py` files (Markdown, JSON evidence, `.retired` forensics) do not block execution and
are recorded in the manifest for provenance.

Pre-execution SHA-256 hash of `scripts/capture_baseline_fixtures.py` is recorded and verified unchanged post-run. Any untracked `.py` file outside this exact allowlist **BLOCKS** execution.

---

## 4. Authoritative Unmodified Baseline Run vs Diagnostic Run

### Phase 1: Authoritative Baseline Run (Unmodified)
- Executed strictly via exact legacy CLI command unchanged:
  ```bash
  python backtests/run_staged_backtest.py --start-date 2023-03-03 --end-date 2023-03-03
  python backtests/run_w4_backtest.py --year 2023 --policy B1 --theta 0.62 --N 10
  ```
- Zero modification to script invocation (`python -c` or `exec(open(...))` wrappers prohibited for primary baseline).
- Source provenance: Clean worktree checks, pre/post static AST repo-local closure SHA-256 source hashes, resolved configs, catalog bounds, and normalized content hashes.

### Phase 2: Supplemental Diagnostic Run (Loaded-Module Capture)
- Executed in a separate diagnostic subprocess with import-tracing hooks to emit child `sys.modules`.
- Output parity check: Normalized outputs compared against Phase 1. If parity passes, loaded modules are marked **VERIFIED**. If parity fails or drift occurs, Phase 1's authoritative baseline is retained, and loaded-module evidence is marked **DIAGNOSTIC_ONLY / UNVERIFIED**.

---

## 5. Dependency Closure Hashing & Input Snapshots

1. **Repo-Local Closure Hashing:** Resolves repo-local Python files imported by entrypoints. Static AST closure must be a subset of observed repo-local loaded modules. SHA-256 hashes of all resolved repo-local source files are verified identical pre- and post-run.
2. **Strategy Config Snapshots:** Saves full resolved `StrategyConfig` dictionary snapshots (`ScoreFanningConfig` and `W4ExitConfig` all 19 fields).
3. **Catalog Identity & Timestamp Bounds:** Saves catalog path (`data/catalog/NQ_v0_2020_2026`), symbol `NQ`, venue `XCME`, loaded bar counts, and first/last `ts_event`/`ts_init` bounds for `1s` and `1m` series.
4. **Offline Predictions Input:** Saves prediction input identity: SHA-256 (`d66a761bd5dbc2c2b7f05d9d74e57a685cc4f12de6eb59f3dcbcd3b3248efdb8`), total row count, and 2023 filtered row count (664,162).
5. **Warmup Evidence Standard:** Loaded bar counts recorded separately from observed bar callbacks dispatched. If callback dispatch cannot be observed non-invasively, manifest records `unavailable_uninstrumented`.

---

## 6. Normalized Content Parity & Tolerances

- **Excluded Volatile Metadata:** `trader_id`, `account_id`, dynamic engine UUIDs, execution wall timestamps, log timestamps.
- **Exact Match Required (0 Tolerance):** Position/trade row counts, event timestamps (`entry_time`, `exit_time`, `ts_init`, `ts_event`), order sides (`BUY`, `SELL`), quantities (`qty`), tick-quantised prices (multiples of `0.25`), and exit reason strings (`SL`, `PT`).
- **Floating-Point Metric Tolerance ($10^{-9}$ Relative):** Aggregate PnL sums, win rates, and profit factors.

---

## 7. Evidence Output Directory Layout & Manifest

```text
backtests/fixtures/baseline_capture_<YYYYMMDD_HHMMSS>/
├── manifest.json                       # Master execution manifest & metadata
├── source_closure_hashes.json          # Pre & post SHA-256 hashes of all AST/sys.modules sources
├── preserved_preexisting/             # Pre-existing target artifacts copied prior to execution
│   └── preservation_manifest.json     # Details of preserved pre-run targets & status classifications
├── fixture_1_score_fanning/
│   ├── status.json                     # SUCCESS / FAILED_UNMODIFIED
│   ├── stdout.log
│   ├── stderr.log
│   ├── resolved_config.json
│   ├── catalog_bounds.json
│   └── results_R2.5.parquet            (results_R5.parquet status: expected_absent_verified)
└── fixture_2_w4_b1/
    ├── status.json                     # SUCCESS / FAILED_UNMODIFIED
    ├── stdout.log
    ├── stderr.log
    ├── resolved_config.json
    ├── catalog_bounds.json
    ├── trades.parquet                  (status: produced_by_current_run)
    └── strategy_trades.parquet         (status: produced_by_current_run)
```
