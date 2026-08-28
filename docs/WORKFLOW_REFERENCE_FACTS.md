# Workflow Reference Facts

Facts that were moved out of `docs/RESEARCH_WORKFLOW.md` because they describe **the state
of the system right now** rather than a rule. They go stale; the rules do not.

Each entry names the command that regenerates or re-verifies it. **Re-derive before relying
on a number here** — do not quote these figures into a study report.

---

## Feature authority bundle

| Fact | Value as of 2026-08-25 | Re-derive with |
|---|---|---|
| Active bundle | `candidate`, `activation_kind: feature_pipeline_v2` | `cat features/authority/active.json` |
| Canonical definitions | 129 | `python -c "import json;print(len(json.load(open('features/authority/candidate/canonical_registry.json'))['definitions']))"` |
| Legacy aliases mapped | 693 | `python -c "import json;print(len(json.load(open('features/authority/candidate/legacy_alias_mapping.json'))['aliases']))"` |
| Bundle composite | `133250b8…` | `cat features/authority/candidate/manifest.json` |

`scripts/activate_feature_pipeline_v2.py` asserts these counts before flipping the pointer,
so a mismatch here means the bundle changed and this table was not updated.

---

## Execution closure membership

The closure is **resolved, never enumerated by hand**:

```bash
python scripts/resolve_execution_manifest.py --study studies/<id>
```

Sampled from `studies/clean_maturity_flip_model_rolling_productivity` on 2026-08-25:

| Fact | Value |
|---|---|
| Files in closure | 109 |
| Markdown in closure | `study:SPEC.md` only |
| Root docs in closure (`AGENTS.md`, `CLAUDE.md`, `CODEX.md`, `docs/*`) | none |

**Consequences worth knowing:**

- Editing repository documentation does **not** stale a study seal.
- `research_workflow/__init__.py` **is** in the closure. A cosmetic `__all__` edit stales a
  sealed study. This has actually happened.
- `GOVERNANCE_AUTHORITY_DATA_FILES` in `scripts/resolve_execution_manifest.py` pulls
  `features/feature_lifecycle_baseline.json` and `features/feature_lifecycle_promotions.json`
  into the closure. The second file is **absent**, which is a legitimate deny-state: a missing
  promotions file grants nothing.

---

## Hashing convention

`canonical_file_sha256()` in `scripts/resolve_execution_manifest.py` normalizes CRLF→LF for
`.py .json .yaml .yml .md .txt .toml .cfg .ini` before hashing (finding **W7**), so a seal
binds content rather than checkout policy. Everything else is hashed byte-exact.

This repository is checked out with `core.autocrlf=true` and carries no `.gitattributes`, so
**raw-bytes and normalized hashes of the same file differ on Windows**:

| `scripts/validate_smoke.py` | Hash |
|---|---|
| raw bytes | `56f8409a…` |
| normalized (what the gates use) | `27963595…` |

**Known defect:** `scripts/tests/test_round2_invariants.py:317` hashes with `read_bytes()`
instead of `canonical_file_sha256`, so four smoke-acceptance tests fail on any Windows
checkout with `SMOKE_VALIDATOR_STALE`. `stability_source_snapshot.json` (root, orphaned — no
code reads it) also holds raw-bytes hashes.

---

## Telemetry cost measurement

Measured 2026-08-24 on a 213,431-event smoke day, generic collector, full surface:

| Configuration | Replay wall time |
|---|---|
| `tracemalloc` off (default) | 5.73 s |
| `tracemalloc` on | 35.24 s |

≈6× — which is why it is opt-in (`NT_TELEMETRY_TRACEMALLOC=1`). Re-measure with
`scripts/benchmark_historical_same_harness.py` rather than quoting these numbers.

---

## Study-specific event ordering

Per-event callback ordering is a property of a **study family**, not of the infrastructure.
It belongs in that study's `SPEC.md` and audit passes.

For the regime-flip family the verified ordering is: completed 1s state update → checkpoint
snapshot → candidate registration → horizon handling → coincident completed-timeframe regime
update. Authority: `studies/clean_maturity_flip_model_rolling_productivity/` SPEC and audit
passes, not this file.

The **generic** guarantees (1s dispatched before its parent 1m, `ts_init` = close, derived
timeframes aggregated from completed lower-timeframe bars) are rules and live in
`docs/RESEARCH_WORKFLOW.md` §17.

---

## Known defects (framework backlog)

**`generic_collector.py` ignores a compiled ordered-barrier `target_contract`.**
The target engine compiles `required_forward_outcomes` (ordered ±ATR barrier specs) into
`compiled_study.json`, and `docs/RESEARCH_WORKFLOW.md` §9 describes a streaming
`forward_outcomes` tracker — but `research_workflow/generic_collector.py` never instantiates
`research_workflow/forward_outcomes/tracker.py`. For every candidate (checkpoint **and**
episode paths) it resolves `disposition` / `target_flip_within_horizon` through its legacy
path (`_track_pending` / `_emit_observation` / `_sweep_elapsed_horizons` / `_on_regime_flip`):
`LABELED_POSITIVE` iff the opposing 1m regime flip lands within the horizon, `LABELED_NEGATIVE`
iff the horizon elapses with no opposing flip, `CENSORED` iff the horizon crosses the RTH
session close. `atr_t` is stored on the row but never used for labeling; no
`favorable ≥ favorable_atr·ATR_T` / `adverse ≥ adverse_atr·ATR_T`, no ambiguous-first-touch.
Any `flip_prediction` study whose `target_contract.target_type` is `composite` with
`ordered_barrier` conditions is therefore collecting the wrong target.
Discovered 2026-08-28 (`studies/deep_pullback_5s_reacceleration_model/`, exhaustive 1s-bar
replay: 51.7% binary-label disagreement, `artifacts/target_replay_diagnostic.json`). Repair
is a collector-runtime change → new runtime closure → re-seal → re-collect. Backlog item;
not yet scheduled (the study that surfaced it closed diagnostic-negative under the correct
target, so there is no live consumer forcing the fix).

**`GenericRollingProductivityProvider` (`Rolling5mProductivityTracker`) requires an exact
contiguous window of printed 1s bars** (301/301 for `window=300s`). NQ 1s bars print only on
traded seconds, so `rolling_300s_*` (and any frozen external score consuming them) is
~73–79% null on this instrument. This is `LINEAGE_MATCH_EXPECTED`, not a defect: the parent
`clean_maturity_flip_model_rolling_productivity` TRAIN surface is itself 72.7% null on these
features and Model-C was fit expecting it (LightGBM native NaN, no complete-case filter).
Recorded here only so a future study does not mistake the null rate for a wiring bug
(`studies/deep_pullback_5s_reacceleration_model/artifacts/rolling_300s_parent_parity_audit.json`).

`scripts/tests/test_round2_invariants.py:317` hashes with `read_bytes()` instead of
`canonical_file_sha256` — see the Hashing convention section above.

---

## Audit history that justifies current limits

| Fact | Source |
|---|---|
| ~60% of blocking audit findings were completeness, not look-ahead (`D1` 22, `C4` 22, `C3` 12, `D4` 9) across ~100 reports | why the audit gate is split |
| One study ran **18 audit passes** and produced a 1,240-line append-only report | `studies/codex_5.6_short_rth_enriched_volume_level_retrain/` |
| The Codex auditor silently missed 14 checklist rules including C4 and D4 | why `scripts/sync_agents.py` exists |
| A cleanup followed a Windows junction out of a disposable worktree and destroyed 179 GB | why `scripts/safe_cleanup.py` fails closed |
