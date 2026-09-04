# QUICKSTART — a Platform V2 study in ten commands

Full manual: `WORKFLOW.md`. Field reference: `docs/RESEARCH_YAML_REFERENCE.md`. Examples: `docs/examples/`.

## 0. Prerequisites

* `~/.nt_research/config.yaml` with `catalog_roots`, `model_root`, `leases_dir`, `worktree_root`
  (`python scripts/research.py data roots` shows it).
* `python scripts/research.py data verify NQ_1S_V2_GLOBEX` → `STATUS: OK`.
* `python scripts/research.py cap generate --check` → `STATUS: OK` (registry current).

## 1. Discover a capability

```bash
python scripts/research.py cap search pullback
python scripts/research.py cap describe tracker.pullback.depth_since_extreme
python scripts/research.py cap list trackers
python scripts/research.py cap list features | head -40
```

Ids you may write in YAML: `context.<name>.tracker` uses the id without the `tracker.` prefix
(`regime.dual_ema`); `features.instances[].feature` uses the canonical feature name (`regime_efficiency`).

## 2. Create a study (branch + sibling worktree + lease + v2 skeleton)

```bash
python scripts/research.py study new my_study --from-question question.md
cd "../Nautilus Trader-my_study"
```

Never edit two studies in one worktree; never work on `main`.

## 3. Edit `studies/my_study/study.yaml`

Start from `docs/examples/checkpoint_classifier.yaml` (grid checkpoints + classifier),
`docs/examples/watch_trigger.yaml` (stateful WATCH → ARMED → entry) or
`docs/examples/multi_arm_outcome.yaml` (barrier race with every semantic declared).
Sections: `study`, `streams`, `context`, `population`, `triggers`, `features`, `outcome`, `chronology`, `model`.

## 4. Compile

```bash
python scripts/research.py study compile --study studies/my_study
```

`STATUS: COMPILED` → `compiled_plan.json` is written. Otherwise the card lists typed gaps:
`MISSING_CAPABILITY` (use `closest`, compose, or propose a capability), `INVALID_PARAMETERIZATION`
(fix the field), `AMBIGUOUS_TEMPORAL_SEMANTICS` / `SEMANTIC_DECISION_REQUIRED` (declare the decision),
`UNAVAILABLE_STREAM` (dataset), `UNSUPPORTED_COMPOSITION` (restructure). No study Python, ever.

## 5. Run through the pre-execution gates

```bash
python scripts/run_governed_study.py --study studies/my_study --through seal --execute-authorized
```

Stops at `NEEDS_CAUSAL_AUDIT` with `_work/controller/audit_packet_causal.json`. `--execute-authorized`
is the real execution gate: it is required for every stage after `seal` (smoke through close) or the
run is `BLOCKED` with `EXECUTION_NOT_AUTHORIZED`; it is a no-op for `--through seal` or earlier.

## 6. Request and ingest the audits

Give the packet to the causal auditor (`lookahead-auditor`); it writes `audit/pass_01.md` ending in an
`AUDIT_SUMMARY_V2` block. Then:

```bash
python scripts/research.py audit ingest --study studies/my_study --type causal --report studies/my_study/audit/pass_01.md
python scripts/run_governed_study.py --study studies/my_study --through seal --execute-authorized   # -> NEEDS_CONTRACT_AUDIT
python scripts/research.py audit ingest --study studies/my_study --type contract --report studies/my_study/audit/contract_pass_01.md
python scripts/run_governed_study.py --study studies/my_study --through seal --execute-authorized   # -> READY_TO_SMOKE
```

## 7. Smoke, TRAIN collection, fit, freeze (detached)

```bash
nohup python -u scripts/run_governed_study.py --study studies/my_study --through freeze --execute-authorized --max-runtime 14400 \
  > studies/my_study/_work/run.log 2>&1 & disown
```

Stages: `smoke` (authorized day) → `collection` (one child per TRAIN year) → `reconcile` → `merge` →
`fit` (or frozen-model scoring) → `freeze`. Re-running the same command resumes; fresh receipts never re-execute.

## 8. Check status

```bash
python scripts/research.py study status --study studies/my_study
```

## 9. Authorized OOS and analysis

```bash
nohup python -u scripts/run_governed_study.py --study studies/my_study --through analyze --execute-authorized --max-runtime 14400 \
  > studies/my_study/_work/run_oos.log 2>&1 & disown
```

`oos` opens `chronology.dev` exactly once after the freeze; `analyze` writes `artifacts/experiment_analysis_v2.json`.

## 10. Close

```bash
python scripts/run_governed_study.py --study studies/my_study --through close --execute-authorized \
  --closure-outcome "<what was found>" --closure-decision "<what happens next>"
```

`artifacts/study_closure.json` is terminal; commit the study directory on its branch and merge with `--no-ff`.

## Starting a new concurrent study

Every study is its own branch and worktree; several run side by side. From the canonical checkout:

```bash
git switch main && git status --short                        # clean main = source of the study
python scripts/research.py study new <id> --from-question question.md
cd "../Nautilus Trader-<id>"                                 # the worktree named in the card; all writes happen here
python scripts/research.py ws list                           # worktrees, owners, lease state (live / stale / dead / released)
python scripts/research.py ws release <id>                   # explicitly release a lease you own
```

Rules and merge-back: `WORKFLOW.md` §M.

## If something blocks

Read the card's `blocker_code` and `reason`, then `studies/my_study/_work/controller/logs/<stage>.log`.
The troubleshooting table is `WORKFLOW.md` §L.
