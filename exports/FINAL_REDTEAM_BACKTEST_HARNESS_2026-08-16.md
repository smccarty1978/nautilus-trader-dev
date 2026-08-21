# Final Independent Red Team — Backtest Harness & Collector Reseal

**Date:** 2026-08-16 · **Reviewer:** independent final Red Team (Claude Opus 5)
**Branch:** `study/Codex_clean_maturity_flip_rolling_5m_productivity`
**Tree reviewed:** working tree at session start (= commit `7cc5e0c`, see §0)
**Method:** independent inspection and execution. No implementation report or prior audit claim was accepted as evidence. No production source code was modified.

---

## VERDICT: `FLOW_BLOCKED`

Two independent bypasses of the audit-provenance chain were demonstrated end-to-end, each producing a
`seal_status: LOCKED` pre-execution seal from evidence that does not establish what the seal claims.
Both were reproduced against a scratch copy of the real study, from the real code, with the real
composite hash.

1. **A single audit report satisfies both mandatory independent gates.** Ingesting one file twice —
   `--type causal` and `--type contract` — produces two `CLEAR` status JSONs and a `LOCKED` seal. The
   recorded `auditor` values (`lookahead_auditor` / `contract_checker`) are hard-coded by the issuing
   function and are not derived from `--author`, so the seal names two reviewers that never existed.
2. **The seal's freshness binding is manufactured by the parser, not declared by the auditor.** On the
   default (non-`--ingest`) route, a report that declares neither `study` nor
   `audited_execution_composite_sha256` still yields a `status.json` whose
   `audited_execution_composite_sha256` is stamped from the tree *as it stands at issuance time*. This
   is not hypothetical: **both live artifacts in this study — `audit/pass_11.md` and
   `audit/contract_pass_10.md` — declare neither field**, and `pass_11.md` states in its own header
   *"Scope hash: not computable in this tool session."*

Because the collector reseal I was asked to perform runs through exactly this chain — and because a
single reviewer authoring both the causal and contract audits *is* finding (1) — **the reseal was not
performed.** Doing so would have manufactured the artifact this review exists to test. See §6.

The backtest harness itself is in good shape: **both golden-equivalence fixtures reproduce exactly**,
independently verified (§3), and every authorization control I attacked on the execution path held
(§4). The blockers are in the audit/seal infrastructure, not in the replay path.

---

## 0. Material change during the review

The working tree was **committed mid-review** by a process other than this reviewer.

| Observation | Evidence |
|---|---|
| At session start: 15 modified + 20 untracked paths | session `git status` snapshot |
| During review: commit `7cc5e0c` "Enhance contract-checker and backtest execution documentation" landed, 83 files | `git reflog HEAD@{0}` |
| A new untracked `ANALYSIS_HARNESS_A0_CONTRACT.md` appeared | `git status --porcelain` |

File **content** was unchanged by the commit (`scripts/run_preexec_audits.py` worktree SHA-256
`988a70dd35277bec…` equals `git show HEAD:` of the same path), so every finding below applies to the
committed tree. Two governance observations follow from it, recorded as W6 and N4.

---

## 1. Evidence table

Severity: **BLOCKING** = an authorization/validity bypass landed · **MAJOR** = a stated acceptance
criterion is not met · **WARNING** = bounded integrity or usability gap · **NOTE** = defect of record.

| # | Sev | Finding | Location |
|---|---|---|---|
| B1 | BLOCKING | One report file, ingested twice under `--type causal` and `--type contract`, satisfies both mandatory gates and yields a `LOCKED` seal. Nothing binds a report to an audit type; nothing detects a duplicate `source_sha256` across the two status files. `auditor` is hard-coded, not taken from `--author`. | `scripts/run_preexec_audits.py:425-449`; `:203`, `:252` |
| B2 | BLOCKING | `_extract_v2_summary` requires only `verdict`. On the default route `issue_*_audit_status_from_report` **stamps** `audited_execution_composite_sha256` from `resolve_execution_manifest(...)` at issuance time instead of verifying an auditor-declared value. The seal's anti-staleness guarantee is therefore self-generated. Affects the live `status.json` and `contract_status.json`. | `scripts/run_preexec_audits.py:63-67`, `:218`, `:232`, `:267`, `:281`; artifacts `audit/pass_11.md:59-60`, `audit/contract_pass_10.md` |
| M1 | MAJOR | A fixture reports `status: SUCCESS` / `baseline_valid: true` while a declared `expectation="produced"` target classified `expected_absent_unverified_due_to_preexisting_target` — and the **stale file's** normalized identity is still copied into the manifest as the reference. `find_latest_baseline` + `_ref_identities` then feed that hash to golden equivalence. Falsifies "a stale or pre-existing baseline cannot be accepted." | `scripts/capture_baseline_fixtures.py:1096-1104`, `:1119-1129`; `scripts/tests/test_nt_runner_backtest.py:590-595` |
| M2 | MAJOR | Both **primary** baseline identities (`results_R2.5.parquet`, `trades.parquet`) are attributed `produced_by_current_run` on **modification-time evidence alone**: they pre-existed, were byte-identical afterwards, and are not quarantined (quarantine applies only to `expectation="conditional"`). The plan's §1 criterion is "timestamp **and** post-run hash comparison"; the hash half is degenerate here. | `scripts/capture_baseline_fixtures.py:114-117`, `:704-746`; manifest `attribution_note` for both targets |
| M3 | MAJOR | `_assert_required_artifacts` runs **after** `run_manifest.json` has already been persisted with `"status": "SUCCESS"`. A run missing a required artifact exits 2 but leaves a SUCCESS manifest on disk. Violates "No successful status without complete required artifacts." | `backtests/nt_runtime/modes/backtest.py:591-604` |
| M4 | MAJOR | The independent finding counter is under-inclusive. Findings written as indented bullets, markdown table rows, em-dash headings, or a `Severity: CRITICAL` line on the row below are **not counted**, so a summary claiming zero findings is accepted and issued `CLEAR`. 4 of 4 such reports were accepted (§5). | `scripts/run_preexec_audits.py:80-104` |
| W1 | WARNING | `simulated_orders` has no counterpart to the `virtual` contract assertion. A virtual strategy forced into it reports `status: SUCCESS` with an empty `trades.parquet`, silently discarding 20 real evaluator trades. | `backtests/nt_runtime/modes/backtest.py:557-573` |
| W2 | WARNING | Worktree gates 1/2 are advisory, so a **modified tracked** file inside a fixture's import closure does not block capture. `strategies/score_fanning_strategy.py` — a closure member — was modified relative to `HEAD` at capture time (`worktree_clean: false`). The "authoritative *unmodified* baseline run" is unmodified only at the *entrypoint*. | `scripts/capture_baseline_fixtures.py:354-405`; manifest `worktree_gates.modified_tracked` |
| W3 | WARNING | Baseline provenance records no third-party library versions (`nautilus_trader`, `pandas`, `pyarrow`, `numpy`, `msgspec`) and no catalog **content** hash — catalog identity is row count + first/last `ts_event`/`ts_init` only. A bar-value change inside the window, or an NT upgrade, is invisible to the frozen baseline. | `scripts/capture_baseline_fixtures.py:812-840`, `:1359-1395` |
| W4 | WARNING | The `strategy_trades.parquet` equivalence assertion is guarded by `if … in result["artifacts"]`, so it passes silently if the harness stops producing that artifact. | `scripts/tests/test_nt_runner_backtest.py:709-714` |
| W5 | WARNING | `.codex/agents/contract-checker.toml` carries `sandbox_mode = "read-only"` while its own instructions state *"You have `Write` for exactly this reason."* The read-only/write contradiction the change set set out to fix is reproduced in the generated Codex rendering. | `.codex/agents/contract-checker.toml:9`; `scripts/sync_agents.py:54-60` |
| W6 | WARNING | Commit `7cc5e0c` committed `scripts/run_preexec_audits.py` together with `audit/status.json`, but that status declares composite `68a0aa2c…` while the committed tree resolves to `2c32545e…`. Violates CLAUDE.md's "commit code together with the audit that audited it, so the scope hash matches the tree." | commit `7cc5e0c`; §2 drift table |
| W7 | WARNING | Residual parser false positive: `- Critical: 0 (none found)` **is** counted as a finding and would raise `FINDING_COUNT_MISMATCH` against a truthful zero-finding summary. | `scripts/run_preexec_audits.py:89`, `:99-102` |
| N1 | NOTE | The canonical example command in the doc agents are told to follow fails: `--param policies_preset=r5_r25` → `UNKNOWN_PARAMETER` (`ScoreFanningConfig` has no such field, and `policies` is structured so it cannot be set via `--param` at all). | `docs/BACKTEST_EXECUTION.md:55` |
| N2 | NOTE | The warmup-DEV-lock branch is unreachable for this study's chronology (train ≤2023, dev 2024, prohibited 2025-26): any run reaching 2024 via warmup must start in 2025, which gate 1 rejects first. Dead but harmless. | `backtests/nt_runtime/data_plan.py:225-241` |
| N3 | NOTE | `--study <sealed collector study>` is unusable in backtest mode — the mode-support gate fires before the data plan — so the `resolve_data_plan` branch is unreachable for that study. Fails closed; no risk. | `backtests/nt_runtime/modes/backtest.py:390-397`; `strategy_binding.py:145-149` |
| N4 | NOTE | 21 `stage=full` collector run directories exist, all `status: RUNNING` with empty `collection/`; the run directory and manifest are created **before** the authorization gate, so every blocked attempt leaves an orphan. 5 were committed in `7cc5e0c`; **2 more were created by my own preflight run**, confirming the test suite itself produces them. No collected data exists in any of them — the gate held every time. | `runs/*_Gemini_clean_maturity_flip_rolling_5m_productivity_full/` |
| N5 | NOTE | Baseline evidence `*.parquet`, `stdout.log`, `stderr.log` are untracked; only the manifests (which carry the reference hashes) are in git. The reference is version-controlled; the corroborating evidence is not. | `git ls-files backtests/fixtures/baseline_capture_20260816_152758/` |

---

## 2. Baselines and equivalence

### 2.1 Baseline validity

Authoritative capture: `backtests/fixtures/baseline_capture_20260816_152758/` — `status: VALID`,
`git_commit 97b97dbab60d`, both fixtures `SUCCESS` / `baseline_valid: true`.

| Check | Result |
|---|---|
| Both fixtures ran to `returncode 0`, empty stderr | **PASS** — `stdout.log` independently corroborates: *"Saved 20 trades for policy R2.5"*, *"Saved 18372 closed positions"*, *"Saved strategy trade log"* |
| Source closure stable across each run, zero drift | **PASS** — `stable_across_run: true`, `drifted_files: []` for both |
| Closure completeness — fixture 1 | **PASS** — 8 files; `utils/__init__.py` present with reason `package_init`. I confirmed no other ancestor `__init__.py` exists on those paths (`utils/runner/__init__.py`, `backtests/__init__.py`, `strategies/__init__.py` are all absent on disk) |
| Closure completeness — fixture 2 | **PASS, independently reproduced** — 3 files. I re-derived the imports: `strategies/w4_exit_strategy.py` imports exactly one repo-local module (`backtests.baseline_flip_parity.strategy`), which imports none. The 3-file closure is provably complete, not asserted |
| Correct attribution | **PARTIAL — M2**. `strategy_trades.parquet` and `resume_manifest.json` were quarantined and are unambiguously produced. The two **primary** artifacts were not quarantined and rest on mtime alone |
| Immutability | **PARTIAL — M1, N5**. Nothing prevents a stale file becoming the reference; evidence copies are untracked |
| Pre-existing preservation & restoration | **PASS** — every pre-existing target restored, `restore_verified_sha256 == pre_sha256` for all; 12 `w4_parity_20{25,26}_B*.parquet` classified `preexisting_stale_unmanaged`, hashed, left in place, never attributed |

### 2.2 Expected-absent handling — cannot a stale file be mistaken for current output?

| Target | Status | Verdict |
|---|---|---|
| `results_R5.parquet` | `expected_absent_verified` — `preexisting: false`, `post: false` | **SOUND.** The path was genuinely clean. `classify_target` returns `expected_absent_verified` only when `path_was_clean = (not preexisting) or quarantined`; a non-quarantined pre-existing file can never reach that status (verified across the full 8-case truth table). The golden test additionally asserts `r5["status"] == "expected_absent_verified"` |
| `w4_parity_2023_B1.parquet` | `expected_absent_verified` — `preexisting: false` | **SOUND**, same mechanism. It is declared `conditional`, so had it pre-existed it would have been quarantined |

Both are correct. The weakness is the mirror case: a stale file at a **`produced`** target (M1).

### 2.3 Golden equivalence — independently reproduced

I did not rely on the shipped test's pass/fail. I re-ran both fixtures through the harness and compared
against the frozen manifest identities myself.

| Fixture | Rows | Baseline normalized SHA-256 | Harness | Result |
|---|---|---|---|---|
| 1 — ScoreFanning, `virtual` | 20 | `5fc80964515084819e8d…` | `5fc80964515084819e8d…` | **PASS** |
| 2 — W4 B1, `simulated_orders`, `trades.parquet` | 18,372 | `4db473610703d8f39fd6…` | `4db473610703d8f39fd6…` | **PASS** |
| 2 — W4 B1, `strategy_trades.parquet` | 18,372 | `3b4840afb506815c9fac…` | matched | **PASS** (compared **unconditionally**, unlike W4) |

Shipped suite, enabled/full mode: `RUN_GOLDEN_EQUIVALENCE=1 pytest scripts/tests/test_nt_runner_backtest.py`
→ **50 collected, 0 failed**. Fixture 1 golden re-run standalone: `3 passed in 4.99s`.

Fixture 1 virtual contract's other half also verified live via the CLI: `nt_positions_report_empty: true`,
`evaluator_tables_empty: ["R5"]`, no `results_R5` artifact, `R2.5` = 20 trades (1 open, 19 closed,
16 SL / 3 PT).

### 2.4 `trader_id` pinning — does it mask a difference?

**Independently assessed: pinning `trader_id` legitimately reproduces the legacy fixture. It does not
mask an economic or execution difference.**

I ran the same full-year W4 replay twice through the harness, changing only `trader_id`, and compared
all 21 columns cell-by-cell against the baseline evidence parquet (18,372 rows each).

| Column | `trader_id="W4-BACKTESTER"` (pinned) | `trader_id="REDTEAM-PROBE"` |
|---|---|---|
| `trader_id` | 0 diffs | **18,372 diffs** |
| `opening_order_id` | 0 diffs | **18,372 diffs** |
| `closing_order_id` | 0 diffs | **18,372 diffs** |
| `entry`, `side`, `quantity`, `peak_qty` | 0 | **0** |
| `ts_init`, `ts_opened`, `ts_last`, `ts_closed`, `duration_ns` | 0 | **0** |
| `avg_px_open`, `avg_px_close` | 0 | **0** |
| `commissions`, `realized_pnl`, `realized_return` | 0 | **0** |
| `strategy_id`, `instrument_id`, `account_id`, `is_snapshot` | 0 | **0** |
| `strategy_trades.parquet` (whole table) | equivalent | **equivalent** |

Exactly three columns move, all of them label columns, and **every economic and temporal field is
invariant to `trader_id`**. The mechanism is confirmed at the library level:

```
TraderId("W4-BACKTESTER").get_tag()      -> 'BACKTESTER'
TraderId("REDTEAM-PROBE").get_tag()      -> 'PROBE'
TraderId("NT-STUDY-ab12cd34").get_tag()  -> 'ab12cd34'
```

NT composes client order IDs as `O-<date>-<time>-<trader-tag>-<strategy-tag>-<seq>` (observed verbatim
in the baseline stdout: `O-20230515-113200-BACKTESTER-000-20165`). The unpinned default is
`NT-STUDY-<random hex>`, whose tag changes every run — so the order-ID columns are *non-deterministic*
without pinning, not *different in substance*.

Two points make this stronger than a simple exclusion, and I confirm both:

- The order-ID **sequence suffix** (`-20165`) is submission-order dependent and is **not** neutralised by
  pinning the tag. It therefore remains a live divergence detector, and it matched exactly across all
  18,372 rows in the pinned run. An execution-path difference would surface there even with `trader_id`
  pinned.
- `strategy_trades.parquet` — the strategy's own blended-PnL log — carries no trader-derived column and
  matched in **both** runs, giving an independent confirmation that is entirely `trader_id`-free.

One caveat to record: `get_tag()` returns the substring after the *last* hyphen, and both legacy runners
use tag `BACKTESTER` (`STAGED-BACKTESTER` and `W4-BACKTESTER` collide). The order-ID columns are
therefore sensitive to the trader **tag**, not to the full `trader_id`; the coverage gained is slightly
narrower than "the comparison now covers `trader_id`". This does not affect the conclusion.

**Verdict: the `trader_id` pin is legitimate and is strictly stronger than the B0 §5 allowance to
exclude the column.**

---

## 3. Harness behaviour — attacks and results

Every command below was executed against the live tree.

| Attack | Result |
|---|---|
| `--param not_a_field=1` | **BLOCKED** `UNKNOWN_PARAMETER` + full declared-field list |
| `--param year=abc` | **BLOCKED** `INVALID_PARAMETER_VALUE … is not an integer` |
| `--param use_trailing_stop=maybe` | **BLOCKED** `INVALID_PARAMETER_VALUE` |
| Unknown strategy id `nope_strategy` | **BLOCKED** `UNREGISTERED_STRATEGY` |
| Arbitrary dotted import `os.system` in backtest mode | **BLOCKED** `UNREGISTERED_STRATEGY_IMPORT_BLOCKED` |
| Collector strategy in backtest mode | **BLOCKED** `does not support mode 'backtest'` |
| Registered FQN `strategies.w4_exit_strategy.W4ExitStrategy` | resolves **through the registry** to `binding_id=w4_exit_strategy` (mode + config binding enforced identically) |
| Dotted path retained for collect mode | **ALLOWED** — `strategies.flip_prediction_collector.FlipPredictionCollector` resolves under `mode="collect"`, as the sealed contract requires |
| `--strategy w4_exit_strategy --study <sealed>` | **BLOCKED** `SEALED_STUDY_STRATEGY_OVERRIDE_BLOCKED` (also blocked at plan level, `resolve_backtest_plan`) |
| Unknown config YAML key | **BLOCKED** `CONFIG_UNKNOWN_KEYS` |
| Missing config file / malformed `--param` / no dates | **BLOCKED** `CONFIG_NOT_FOUND` / `INVALID_PARAM` / `MISSING_REQUIRED_INPUT` |
| `--resume` | **BLOCKED** `UNSUPPORTED_FEATURE` — explicit error, not silently ignored |
| `--dry-run` determinism | **PASS** — two invocations byte-identical; nothing written to `runs/` |
| Invalid execution modes (7 variants incl. `fill_model=tick`) | **BLOCKED** with distinct actionable errors |
| W4 forced into `virtual` | **BLOCKED** `VIRTUAL_CONTRACT_UNSATISFIED`; manifest left `RUNNING`, never SUCCESS |
| ScoreFanning forced into `simulated_orders` | **ACCEPTED — W1.** `status: SUCCESS`, empty `trades.parquet`, 20 real virtual trades dropped |
| Required artifact missing at gate time | **M3** — raises and exits 2, but `run_manifest.json` on disk already reads `status: SUCCESS` |

### 3.1 Governance retention after the `resolve_catalog_plan` extraction

| Window | Study-bound `resolve_data_plan` | Generic `resolve_catalog_plan` |
|---|---|---|
| 2023-06-01 (train) | ALLOWED | ALLOWED |
| 2024-06-01 (dev) | **BLOCKED** `OOS_LOCKED_UNTIL_FREEZE` | ALLOWED |
| 2025-06-01 (prohibited) | **BLOCKED** `UNAUTHORIZED_EXECUTION_DOMAIN` | ALLOWED |
| 2025-01-02, warmup reaching 2024 | **BLOCKED** `UNAUTHORIZED_EXECUTION_DOMAIN` | ALLOWED |
| 400-day warmup from 2023-01-02 → load start 2021-11-28 | ALLOWED (all train years) | ALLOWED |

Collector governance is fully retained; the generic resolver is correctly free of it. `bound == generic`
for an authorized window (asserted by the shipped test and confirmed here), so the split changed gates
only, not values. `modes/collect.py:149,176` still calls `resolve_data_plan` and `build_engine` with no
`execution_mode`, so it inherits `ExecutionMode.collector_default()`.

I verified the collector-default claim against the installed library rather than the docstring:

```
nautilus_trader 1.230.0 → BacktestEngine.add_venue defaults:
  bar_execution = True ; bar_adaptive_high_low_ordering = False
ExecutionMode.collector_default() → bar_execution=True, bar_adaptive_high_low_ordering=False
```

Collector venue semantics are byte-for-byte what they were before the contract existed. **PASS.**

---

## 4. Capture and audit infrastructure

### 4.1 Capture runner

| Aspect | Result |
|---|---|
| Gate 3 — module-shadowing untracked `.py` | **PASS**. Injecting an untracked `utils/runner/data.py` into the 11-path protected closure → `passed: False`, `disallowed: ['utils/runner/data.py']`. New harness code outside every closure is recorded under `untracked_py_outside_closure`, not blocked. Strictly stronger than a name allowlist, as claimed |
| Gate 1/2 — modified tracked closure file | **W2**. Advisory only; does not block |
| Allowlist | 2 entries, both the capture tooling itself; neither is inside any fixture closure |
| Closure resolver — package `__init__.py` | **PASS**, verified against the filesystem (§2.1) |
| Closure resolver — dynamic module handling | Mechanism is sound (`_dynamic_module_candidates` keeps a dotted string only if it resolves to a repo file, and also considers the `pkg.mod` head of `pkg.mod.Class`). Deliberately over-inclusive, which is the safe direction. Neither fixture actually exercised it — both closures are `entrypoint`/`static_import`/`package_init` only, so the rule is **untested by the shipped baselines** |
| Source-hash comparison | **PASS** for repo-local Python. **W3** for libraries and catalog content |

### 4.2 `run_preexec_audits.py --ingest` attack matrix (22 cases)

**REJECTED (18):** malformed summary JSON · missing summary · duplicate summary blocks · wrong study ·
stale composite · composite undeclared · study undeclared · `CLEAR` with `blocking=2` · negative counts ·
zero claimed with a `### BLOCKING:` heading present (`FINDING_COUNT_MISMATCH`) · bad verdict token ·
non-Markdown source · empty report · self-asserted (source inside `audit/`) · destination exists.
A rejected report leaves **no** artifact behind — the ordering bug is genuinely fixed.

**ACCEPTED (should not have been — 4, all M4):**

| Report body claiming `blocking: 0` | Outcome |
|---|---|
| `  - BLOCKING: sealed closure omits X` (indented bullet) | ACCEPTED, `verdict=CLEAR` |
| `\| F1 \| BLOCKING \| closure omits X \|` (table row) | ACCEPTED, `verdict=CLEAR` |
| `### BLOCKING — sealed closure omits X` (em-dash) | ACCEPTED, `verdict=CLEAR` |
| `### Finding 1` / `Severity: BLOCKING` (next line) | ACCEPTED, `verdict=CLEAR` |

### 4.3 Heading/count parser — the explicit requirement

Isolated parser probe, 18 cases:

| Input | Counted | Correct? |
|---|---|---|
| `## Critical findings` | 0 | ✔ required behaviour |
| `- Critical: 0` | 0 | ✔ required behaviour |
| `- **Critical:** 0` | 0 | ✔ (emphasis stripped from both ends) |
| `- Critical: none` / `- Warning: N/A` | 0 | ✔ |
| `### CRITICAL: look-ahead in feature snap` | 1 | ✔ |
| `- **CRITICAL: look-ahead in feature snap**` | 1 | ✔ |
| `- Critical: 0 (none found)` | 1 | ✘ **W7** false positive |
| indented / blockquote / table / em-dash / next-line severity | 0 | ✘ **M4** false negatives |
| inside a fenced code block | 1 | over-count, safe direction |

The stated requirement — *"does not treat `Critical: 0` or section headings as findings"* — **is met**.
The broader property — *"an audit report cannot claim zero findings while hiding findings in headings,
formatting, or duplicate sections"* — **is not**: duplicate summary blocks are blocked, but formatting
evasion is not.

### 4.4 contract-checker instruction/permission consistency

| Harness | Declared tools | Instructions | Consistent? |
|---|---|---|---|
| `.claude/agents/contract-checker.md` | `[Read, Grep, Glob, Write]` | "You have `Write` for exactly this reason" | **YES** — the original contradiction is fixed |
| `.agents/agents_staging/contract-checker.md` | (body only, no tool block) | same | n/a |
| `.codex/agents/contract-checker.toml` | `sandbox_mode = "read-only"` | same body, asserting it has `Write` | **NO — W5** |

The body's "If you cannot write" fallback routes to the ingestion path, which materially mitigates W5;
the defect is that the generated Codex artifact asserts a capability its own metadata denies.
`scripts/sync_agents.py` propagates the body but takes `sandbox_mode` from a hand-maintained
`CODEX_META` table that was not updated.

---

## 5. Adversarial falsification summary

| Claim to falsify | Outcome |
|---|---|
| A stale or pre-existing baseline can be accepted | **FALSIFIED — the claim holds (M1).** Demonstrated: `SUCCESS` / `baseline_valid: true` with a stale file's hash published as the reference |
| A source dependency can change outside the captured closure | **FALSIFIED — the claim holds (W3).** Repo-local Python is fully hashed pre/post, but library versions and catalog **content** are not captured |
| A dynamic strategy/module bypasses registration or sealing | **NOT falsified.** Backtest mode is registry-only; collect mode's strategy identity comes from `compiled_study.json`, which is inside the sealed closure, so changing it changes the composite and invalidates the audits |
| Virtual output can be misreported as broker positions | **Partially (W1).** The literal direction is blocked (`VIRTUAL_CONTRACT_VIOLATED` if a "virtual" strategy places orders). The inverse is not: a virtual strategy under `simulated_orders` reports SUCCESS with an empty broker table and drops its real output |
| A warmup/partition path bypasses collector governance | **NOT falsified.** All four gates retained and firing (§3.1) |
| An audit report can claim zero findings while hiding findings | **FALSIFIED — the claim holds (M4).** 4 of 4 formatting variants accepted as `CLEAR` |
| Code changed after audit can still seal | **NOT falsified for content drift** — `PREEXEC_AUDIT_STALE` fires correctly. **But B2 defeats the intent**: because the composite is stamped rather than declared, re-running the issuer after a change silently re-binds the audit to the new code |

---

## 6. Collector reseal — NOT PERFORMED

The instruction was to reseal *"if and only if the harness review has no blocker."* It has two (B1, B2),
and both sit directly on the reseal path. Two further reasons make proceeding wrong regardless:

1. **I am one reviewer.** Authoring both the causal and the contract audit would *be* finding B1 — the
   exact defect this review identified. The resulting seal would record `lookahead_auditor` and
   `contract_checker` as separate authorities that did not exist.
2. **The freshness binding would be manufactured, not asserted.** Under B2 my status JSONs would carry a
   composite the parser stamped, not one I declared and the tool verified.

### Current collector state (independently measured, not taken from any report)

| Item | Measured |
|---|---|
| Current execution composite | `2c32545e1b8eb2a417d7eafdda809215216b3903ce68e292c1a8e729f2d01301` (53/53 files, coverage 100.0%) |
| Causal `status.json` — pass 11 | `CLEAR`, declares `68a0aa2ceb20…` → **stale by 1 file**: `scripts/run_preexec_audits.py` |
| Contract `contract_status.json` — pass **10** | `CLEAR`, declares `f01abb545ab4…` → **stale by 4 files**: `data_plan.py`, `engine_builder.py`, `strategy_binding.py`, `run_preexec_audits.py`. **No contract pass 11 exists** |
| `preexec_audit_seal.py --study …` | **REFUSES** — `PREEXEC_AUDIT_STALE: Execution code modified after Causal Audit!` ✔ |
| `preexec_audit_seal.py --verify-only` | **REFUSES** — `data_plan.py was modified after audit seal!` ✔ |
| `scripts/research_preflight.py` | **`BLOCKED`**, gate `CAUSAL_INVARIANTS`, `264 passed / 1 failed` — the single failure is `test_audit_seal_valid_and_tamper_detection` detecting exactly this staleness |
| Bounded sealed smoke | **NOT RUN** — collect mode verifies the seal first; correctly unreachable |
| `stage=full` run directories | 19, all `status: RUNNING`, all `collection/` empty. **No collected data exists.** The authorization gate held on every attempt |

The gates are behaving correctly. The collector is not runnable, and should not be resealed until B1 and
B2 are closed.

---

## 7. Tests and commands run

| Command | Result |
|---|---|
| `RUN_GOLDEN_EQUIVALENCE=1 pytest scripts/tests/test_nt_runner_backtest.py` | 50 collected, **0 failed** |
| `RUN_GOLDEN_EQUIVALENCE=1 pytest … -k "score_fanning_harness_matches or both_fixtures_have_valid or closures_record"` | **3 passed** in 4.99s |
| `pytest test_capture_baseline_fixtures test_audit_report_ingestion test_round2_invariants test_spec_fidelity_and_oos_lock test_audit_seal_guard test_guardrail_mutations` | **131 passed, 1 failed** (`test_audit_seal_valid_and_tamper_detection` — expected staleness) |
| `python scripts/research_preflight.py --study studies/Gemini_…` | `BLOCKED` / `CAUSAL_INVARIANTS` / 264 passed, 1 failed |
| `python scripts/preexec_audit_seal.py --study …` and `--verify-only` | both refuse with `PREEXEC_AUDIT_STALE` ✔ |
| `python scripts/resolve_execution_manifest.py --study …` | composite `2c32545e…`, 53/53, coverage 100.0% |
| `python backtests/run_backtest.py --config backtests/configs/score_fanning_2023_03_03.yaml` | SUCCESS, 20 R2.5 trades, positions report empty |
| Independent W4 probe, `trader_id="W4-BACKTESTER"` (full-year replay) | `trades` + `strategy_trades` both equivalent; 21/21 columns zero diffs |
| Independent W4 probe, `trader_id="REDTEAM-PROBE"` (full-year replay) | exactly 3/21 columns differ (`trader_id`, `opening_order_id`, `closing_order_id`); all 18 economic/temporal columns 0 diffs; `strategy_trades` equivalent — §2.4 |
| 8 CLI negative/authorization attacks | all blocked as tabulated in §3 |
| 22-case ingestion attack matrix | 18 rejected, 4 accepted (M4) |
| 18-case parser probe | required behaviours correct; M4 + W7 confirmed |
| 8-case `classify_target` truth table | mtime-only attribution confirmed (M2) |
| Fabricated-capture probe (runner writes nothing, stale target present) | `SUCCESS` / `baseline_valid: true` with stale identity (M1) |
| Dual-ingest probe (one report → both gates) | `LOCKED` seal generated (B1) |
| Twin-report probe (pre-`--ingest` route) | `LOCKED` seal generated — B1 pre-dates the new path |
| Unbound-summary probe (no `study`, no composite) | composite stamped from current tree; `LOCKED` seal generated (B2) |
| Artifact-completeness ordering probe | `MissingArtifactError` raised, manifest on disk still `SUCCESS` (M3) |
| `--param policies_preset=r5_r25` (the documented example) | `UNKNOWN_PARAMETER` (N1) |

All adversarial probes ran against scratch copies (`%TEMP%/rt_*`) or scratch output directories. No
production source code, no audit report, no status JSON, no seal and no baseline was modified by this
review.

**Side effects this review did produce, disclosed in full** (`git status` at close):

| Path | Cause |
|---|---|
| `studies/…/audit/preflight.json` (modified) | written by the required `scripts/research_preflight.py` run (§6) |
| `studies/…/audit/failure_packet.json` (modified) | same run; records the expected `CAUSAL_INVARIANTS` failure |
| `runs/20260816_182918_…_full/`, `runs/20260816_183011_…_full/` (new) | orphan `stage=full` directories created by the preflight test suite before the authorization gate — see N4 |
| `exports/FINAL_REDTEAM_BACKTEST_HARNESS_2026-08-16.md` (new) | this report |

`ANALYSIS_HARNESS_A0_CONTRACT.md` is untracked but **not** mine — it appeared during the review (§0).

---

## 8. Exact smallest remediations

**B1 — bind a report to one audit type and forbid reuse.**
In `_extract_v2_summary`, require an `audit_type` field ∈ {`causal`,`contract`}. In
`ingest_external_audit_report` (`:381-385`), reject when `summary["audit_type"] != audit_type`. In both
`issue_*_audit_status_from_report`, reject when the sibling status file already records the same
`audit_report_sha256`. Add `auditor: str` as a required parameter and pass `--author` through
(`:430`) instead of defaulting to the hard-coded label.

**B2 — verify the composite, never stamp it.**
Make `study` and `audited_execution_composite_sha256` mandatory in `_extract_v2_summary` for **both**
routes. In `issue_causal_audit_status_from_report:218` and
`issue_contract_audit_status_from_report:267`, compare the summary-declared composite to
`resolve_execution_manifest(...)` and raise `AuditArtifactParseError` on mismatch, exactly as
`ingest_external_audit_report:407-412` already does. Re-issue `pass_11` / `contract_pass_11` only after
their authors declare the composite themselves.

**M1 — a `produced` target must actually be produced.**
In `capture_fixture:1119`, after classification:
`if any(s.spec.expectation == "produced" and s.status != STATUS_PRODUCED for s in states): status = "FAILED_UNMODIFIED"`.
Additionally filter `_ref_identities` (`test_nt_runner_backtest.py:590-595`) to
`t["status"] == "produced_by_current_run"`.

**M2 — quarantine `produced` targets too.**
Change `TargetSpec.quarantine_required` (`:114-117`) to `self.expectation in ("produced", "conditional")`.
This makes `path_was_clean` true, so attribution comes from the file's existence after a clean start
rather than from mtime. Then delete the mtime-only branch at `:730-735`.

**M3 — assert before persisting SUCCESS.**
Move `_assert_required_artifacts(...)` (`modes/backtest.py:604`) above the final
`_write_json(run_dir / "run_manifest.json", manifest)` at `:602`, and wrap it so a failure rewrites the
manifest with `status: "FAILED_INCOMPLETE_ARTIFACTS"` before re-raising.

**M4 — widen the finding regex.**
In `_FINDING_HEADING` (`:80-87`): anchor as `^\s*(?:#{1,4}|[-*])\s+`, and accept `[:–—-]` as
the separator instead of `:` alone. Add a second pattern for table rows
(`^\s*\|[^|]*\|\s*(?:CRITICAL|BLOCKING|WARNING)\s*\|`) and for a standalone
`^\s*(?:\*\*)?Severity(?:\*\*)?\s*:\s*(CRITICAL|BLOCKING|WARNING)` line.

**W1 — give `simulated_orders` a counterpart assertion.**
In `modes/backtest.py:557`, before writing outputs: if the strategy exposes a non-empty `evaluators`
collection while `positions_report_rows == 0`, raise
`SIMULATED_CONTRACT_VIOLATED: strategy produced N virtual evaluator trades and zero NT positions; declare order_handling='virtual'`.

**W2 — make closure members blocking.**
In `check_worktree_gates:385`, add modified/staged tracked files that are inside `protected_paths` to
`disallowed`. Files outside the closure stay advisory.

**W3 — record the rest of the environment.**
In the manifest (`:1380`), add
`{p: importlib.metadata.version(p) for p in ("nautilus_trader","pandas","pyarrow","numpy","msgspec")}`,
and extend `_run_catalog_probe` to record the SHA-256 of each catalog parquet partition intersecting the
load window.

**W4 — make the assertion unconditional.**
`test_nt_runner_backtest.py:709` — replace the `if` with
`assert "strategy_trades" in result["artifacts"], "harness produced no strategy_trades artifact"`.

**W5 — fix the generated Codex metadata.**
`scripts/sync_agents.py:58` — set `contract-checker`'s `sandbox_mode` to `"workspace-write"`, or keep
`read-only` and have `render_codex` substitute a harness-specific note; then re-run
`python scripts/sync_agents.py`.

**W6 — re-issue evidence against the committed tree.** Follow B2's remediation, then commit the new
`pass_NN.md` + `contract_pass_NN.md` + both status JSONs in a single commit with the code they audit.

**W7 — loosen the count-only guard.**
`_COUNT_ONLY_TITLE` (`:89`) → `r"^(?:\d+|none|n/?a|zero)\b[\s.()\w]*$"`.

**N1 — fix the documented example.**
`docs/BACKTEST_EXECUTION.md:55` — drop `--param policies_preset=r5_r25`; `policies` is a structured
field and the legacy list is already the default.

---

## 9. What is solid

Stated plainly, because the blockers are narrow and it would be misleading to leave the impression that
the harness is broken:

- **Both golden fixtures reproduce exactly**, verified by me end-to-end, including a 21-column
  cell-by-cell comparison on 18,372 W4 positions with zero differences.
- **Fixture 2's 3-file closure is provably complete** — I re-derived the import graph rather than
  trusting the manifest.
- **Every execution-path authorization control held**: sealed-study override, arbitrary-import
  execution, unknown parameters and strategies, prohibited/DEV years, warmup domain, unsupported
  features.
- **The collector venue contract is byte-identical to pre-B1 behaviour**, verified against the installed
  `nautilus_trader` 1.230.0 signature defaults rather than a docstring.
- **The seal correctly refuses every stale state it was shown**, and the full-run gate blocked all 19
  collection attempts with zero data written.
- **18 of 22 audit-ingestion attacks were rejected**, including the whole self-assertion, wrong-study,
  stale-composite, duplicate-block and overwrite classes — and a rejected report now leaves no artifact.
- The implementation report's self-assessment is **honest**: it declared the seal stale rather than
  claiming a `CLEAR`, and it flagged the `trader_id` argument for exactly the scrutiny it received.
