# Governed study controller

`python scripts/run_governed_study.py --study studies/<id> --through seal` is the compact,
resumable operator surface over the existing governed lifecycle. It does not create a second
collector, audit implementation, analysis loader, or seal path.

| State | Meaning | Intervention |
| --- | --- | --- |
| `NEEDS_COMPILE` through `NEEDS_PREFLIGHT`, then `NEEDS_TESTS` | A stale or missing deterministic gate | Order is compile, prepare, readiness, canonical preflight, test-evidence extraction; tests are not rerun. |
| `NEEDS_CAUSAL_AUDIT` / `NEEDS_CONTRACT_AUDIT` | Current independent review is missing | Give the generated compact packet to the named independent auditor; controller never judges it. |
| `READY_TO_SEAL` | Both current audit JSON artifacts are CLEAR | Controller uses the existing seal implementation. |
| `READY_TO_COLLECT` onward | Execution requires an approved study-specific operation | Register/use the standard governed API; OOS remains accessible only through `assert_oos_open`. |
| `PHASE_D_MODELING_READY_NOT_AUTHORIZED` | A tracked, hash-validated legacy TRAIN handoff is complete through its declared frozen phase | The controller stops before any lifecycle action and returns the manifest's exact next phase; explicit semantic authorization is required. |

Use `--inspect` or `--dry-run` for a non-mutating state card, `--json` for one compact JSON
record, and repeat `--owned-path <repo-relative-path>` only for intentional local edits. Before
any controller write, unowned dirty files produce `WORKTREE_CONTAMINATION`; nothing is reverted.
This enforces **ONE_WRITER_PER_WORKTREE**: one implementation owner, one causal auditor, and one
contract auditor (an optional repo scout is read-only; replacements are exceptional).

For a legacy handoff manifest with no self-hash field, the controller requires its working bytes
to match the tracked Git index blob and independently validates every declared artifact path, file hash, and any
declared Parquet row count/schema. Missing compiler lineage alone never activates this exception:
the modern compiler must specifically return `SEMANTIC_DECISION_REQUIRED` in its non-writing
projection, and the current seal and execution composite must still verify.

The controller saves detailed evidence under `studies/<id>/_work/controller/`: `status.json`,
`progress.json`, current `failure_packet.json`, and audit packets. Verbose child output is stored
as `logs/<stage>.log`; compact stdout contains only status, state, stage, artifact, hash, and
next state. This changes the normal interaction from repeatedly pasting lifecycle/audit output
to reading one card and acting only at a named gate, substantially reducing model context while
preserving the existing causal, audit, seal, and OOS guards.

Supported `--through` names are `compile`, `prepare`, `readiness`, `preflight`, `tests`,
`causal_audit`, `contract_audit`, `seal`, `collection`, `reconcile`, and `analyze`. Fresh artifacts are skipped; fingerprint drift restarts at the earliest affected lifecycle stage
and continues only downstream. Interrupted work resumes from artifacts rather than rerunning
completed gates. `--max-runtime`, `--stale-progress-timeout`, and `--rss-limit-mb` are retained
on the controller and the verbose-child adapter uses `scripts.run_bounded_study.monitor_process`.
No real collection or OOS execution is initiated by the default CLI.

Late execution stages are deliberately conservative: collection, reconciliation, and analysis
are fresh only with a controller receipt under `_work/controller/receipts/` whose output hashes
and current execution composite validate. A collection receipt also names every intended
partition and PASS status. Ordinary smoke/day run manifests never satisfy collection. The
registered operation must return this output contract; otherwise the controller reports a
capability/runtime packet instead of inferring completion.

The production collection leaf calls only `collection.build_year_partitions` and
`collection.collect_partition`. It records one atomic partition record and progress update
after each completed partition, and revalidates a resumed record against its `PartitionSpec`,
current verified pre-execution seal identities, terminal `run_manifest.json`/`status.json`, primary dates, and the three
collection artifacts. Candidate and observation bytes must match both the run and collection
manifest hashes; the terminal manifest and status bytes are receipt evidence too. A missing or
mismatched run launch identity is rejected. A corrupt or stale partition is rerun by itself; it is never promoted from a
record alone. Reconciliation requires exactly the currently declared partition set, uses both
`partitioning.reconcile_partitions` and `scripts.reconcile_runs.classify_run`, and persists
the resulting run classifications and artifact hashes.

Production actions never set synthetic artifact trust. The test-only `synthetic_test` escape
is available solely on explicitly constructed fixture actions. Analysis requires all three
explicit inputs (`--analysis-frame`, `--score-columns-json`, `--target-column`), binds the
frame and canonical configuration hashes, and invokes `research_workflow.analysis.analyze_results`
so its `assert_oos_open` guard remains authoritative. Controller action stdout/stderr and
tracebacks stay in `_work/controller/logs/`; receipts record the stage log path/hash when one
exists.

## Stages (platform-v2, item 04)

The controller is the sole operator surface. `--through` accepts, in order:

`compile, prepare, readiness, preflight, tests, causal_audit, contract_audit, seal, smoke,
collection, reconcile, merge, fit, freeze, oos, analyze, close`.

Every stage from `smoke` on is receipt-bound (`_work/controller/receipts/<stage>.json`, hash-bound
to the execution composite and to the stage's output bytes). Re-executing a stage invalidates
every downstream receipt. `close` is terminal: a valid `artifacts/study_closure.json` is the
authority and is never rewritten.

| Stage | Owns | Notes |
| --- | --- | --- |
| `smoke` | bounded 1-day real run + reconciliation | `--execute-authorized` |
| `merge` | deterministic merge of reconciled TRAIN partitions | writes `_work/controller/merged/{candidates,observations}.parquet` + `identity.json` |
| `fit` | governed TRAIN fit via `modeling.fit_models` (+ `model_selection` when declared) | label column is declared by the target contract (`label_column`) or passed with `--label-column`; never guessed |
| `freeze` | `modeling.freeze_train_artifacts` from the controller's own fit | TRAIN-only thresholds/deciles; binds the merge identity |
| `oos` | OOS collection | opens only through `experiment.assert_oos_open`; partition records under `_work/controller/partitions/oos/` |
| `close` | records an operator-supplied terminal decision | `--closure-outcome` + `--closure-decision`; the controller never decides the science |

`scripts/run_research_workflow.py`, `scripts/run_partitioned_train_collection.py` and
`scripts/reconcile_study_capabilities.py` are deprecated shims that print a card and exit 2.
`research_workflow/lifecycle.py` and `workflow_engine.py` remain internal leaves, not operator
entry points. Sealed studies keep their historical execution authority at their own commit.
