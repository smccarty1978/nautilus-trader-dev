# Platform V2 research YAML reference

Generated from `research_workflow/grammar/spec.py` by `scripts/gen_yaml_reference.py` -- do not hand-edit.
The grammar is the authority; the compiler (`research study compile`) is the only validator. Every section is strict:
unknown keys are rejected except where noted (`context.<name>` and `features.instances[]` accept free parameters).

Duration strings: `'600s'`, `'5m'`, `'1h'`. References: `tracker.field`, `epoch.T`, `state`, `age(STATE)`.
Predicate language: comparisons, `and/or/not`, `in [..]`, event tests `x.flipped(to=-1)`, `x.changed`, `x.turned(from=, to=)`, `x.new_leg`, `x.terminated`; no arithmetic.

| Field | Type | Required | Default | Allowed | Meaning | Causal implication | Example |
|---|---|---|---|---|---|---|---|
| `study` | object (StudySection) | yes |  |  | Identity section. | None. | `study: {id: my_study, tier: 2, question: "..."}` |
| `study.id` | str | yes |  |  | Study identifier; also the directory name under studies/. | None. | `id: v2_shape_a_flip_180s` |
| `study.tier` | int | no | 2 |  | Ceremony tier 1-3 (see CLAUDE.md §7). | Tier 3 requires repo-scout closure evidence before sealing. | `tier: 2` |
| `study.question` | str | yes |  |  | The research question in one sentence. | Audits read it to judge whether the population and outcome answer it. | `question: "Does causal state at T predict a 1m regime flip within 180s?"` |
| `study.description` | str | null | no | None |  | Free text. | None. | `description: fresh v2 study` |
| `streams` | list[object (StreamSpec)] | yes |  |  | Datasets and timeframes; the first is the execution stream. | Only external timeframes declared in the DatasetSpec are read from disk; the rest are host-derived complete buckets. | `streams: [{dataset: NQ_1S_V2, timeframes: [1s, 1m]}]` |
| `streams[].dataset` | str | yes |  |  | Committed DatasetSpec id (research/datasets/<id>.yaml); never a path. | The plan binds the dataset logical digest; readiness verifies bytes. | `dataset: NQ_1S_V2` |
| `streams[].instrument` | str | null | no | None |  | Instrument symbol; defaults to the dataset's instrument. | None. | `instrument: NQ` |
| `streams[].timeframes` | list[str] | yes |  |  | Timeframes to deliver ('1s', '5s', '1m', '5m'). Only timeframes declared in the DatasetSpec are external; others are host-derived complete buckets. | Only the finest external timeframe of the execution instrument carries epochs; every coarser external timeframe is a context stream visible strictly before the epoch. | `timeframes: [1s, 1m]` |
| `streams[].role` | enum | no | execution | 'execution', 'context' | execution (the first stream by default) or context. | Context bars are queued until an execution bar with a strictly later ts_init arrives. | `role: context` |
| `streams[].same_ts` | enum | no | unavailable | 'unavailable', 'available' | Opt-in to same-timestamp visibility of a context stream. | 'available' is refused with SEMANTIC_DECISION_REQUIRED until a tie-order policy is proven. | `same_ts: unavailable` |
| `population` | object (PopulationSpec) | yes |  |  | Who is a candidate and when a decision epoch occurs. | Everything here is evaluated at T from state visible at T. | `population: {session: RTH, cadence: completed_1s, qualify: "regime_1m.dir != 0", direction: regime_1m.dir}` |
| `population.session` | str | no | RTH |  | Session name from the session table (RTH, ALL, ...). | Candidates are emitted only inside the session; outcome censoring uses outcome.session when given. | `session: RTH` |
| `population.cadence` | str | object (GridCadence) | no | completed_1s |  | 'completed_1s' | 'completed_1m' | a grid {every, anchor, max_age, index_column}. | Epochs occur at bar close (ts_init); a grid anchors checkpoints to a tracker field (e.g. regime start). | `cadence: {every: 5s, anchor: regime_1m.start_ns, max_age: 1800s}` |
| `population.cadence.every` | str | yes |  |  | Grid spacing. | None. | `every: 5s` |
| `population.cadence.anchor` | str | yes |  |  | Tracker field the grid counts from. | Must be known at the epoch. | `anchor: regime_1m.start_ns` |
| `population.cadence.max_age` | str | null | no | None |  | Stop emitting checkpoints past this age. | None. | `max_age: 1800s` |
| `population.cadence.index_column` | str | no | checkpoint_index |  | Output column carrying the checkpoint index. | None. | `index_column: checkpoint_index` |
| `population.qualify` | str | null | no | None |  | Predicate over tracker fields at the epoch; event tests are not allowed here. | Only state visible at T; any outcome column in a qualify is impossible by construction. | `qualify: "regime_1m.age_s >= 120s and excursion.mfe_atr >= 1.0"` |
| `population.direction` | str | null | no | None |  | Reference giving the candidate direction (+1/-1). | Read at T. | `direction: regime_1m.dir` |
| `population.anchor_identity` | str | null | no | None |  | Reference stamped as regime_start_ns (part of the row key). | None. | `anchor_identity: regime_1m.start_ns` |
| `context` | map[str -> object (ContextTrackerSpec)] | no | dict() |  | Named tracker instances (stateful causal state). | Trackers only see bars closed at or before the epoch. | `context: {regime_1m: {tracker: regime.dual_ema, timeframe: 1m}}` |
| `context.<name>.tracker` | str | yes |  | free keys | Registered tracker capability id without the 'tracker.' prefix; other keys are that tracker's parameters (see `research cap describe tracker.<id>`). | Trackers update on bar close of their stream and are read at the epoch; their WARMUP_BARS extend the warmup window. | `regime_1m: {tracker: regime.dual_ema, timeframe: 1m}` |
| `context.<name>.instrument` | str | null | no | None | free keys | Instrument for multi-instrument context. | Cross-instrument bars are context streams (strictly before the epoch). | `instrument: ES` |
| `triggers` | enum | object (TriggerGraphSpec) | no | every_candidate | 'every_candidate' | 'every_candidate' or a trigger graph. | None. | `triggers: every_candidate` |
| `triggers.cadence` | str | null | no | None |  | Evaluate the graph on 'completed_1s' bars or on 'tracker_events'. | None. | `cadence: completed_1s` |
| `triggers.states` | map[str -> object (TriggerStateSpec)] | no | dict() |  | Named states with enter/expire predicates; OBSERVE is implicit. | Predicates read tracker state and edge events of the current epoch only. | `states: {WATCH: {enter_when: "pullback.depth_atr >= 1.0"}}` |
| `triggers.states.<name>.enter_when` | str | yes |  |  | Predicate to enter the state. | None. | `enter_when: "state == WATCH and regime_5s.dir == -regime_1m.dir"` |
| `triggers.states.<name>.expire_when` | str | null | no | None |  | Predicate that leaves the state (back to OBSERVE). | age(STATE) counts from the entering epoch. | `expire_when: "age(WATCH) > 600s"` |
| `triggers.states.<name>.from` | list[str] | no | list() |  | Allowed predecessor states. | None. | `from: [WATCH]` |
| `triggers.states.<name>.chain` | bool | no | False |  | May be entered in the same sub-epoch as its predecessor. | None. | `chain: true` |
| `triggers.entry` | object (EntrySpec) | null | no | None |  | The entry rule: when, reference price, per-watch limits. | Entry fires on an edge; the reference is resolved on the NEXT bar (next_bar_open). | `entry: {when: "state == ARMED and regime_5s.turned(from=-regime_1m.dir, to=regime_1m.dir)", reference: next_bar_open, max_per_watch: 1}` |
| `triggers.entry.when` | str | yes |  |  | Entry predicate (usually an edge test). | None. | `when: "state == ARMED and x.turned(to=1)"` |
| `triggers.entry.reference` | str | no | next_bar_open |  | Entry reference from research_workflow/entry_references.py. | Only next_bar_open / next_printed_bar_open are executable; decision_close is a research mark. | `reference: next_bar_open` |
| `triggers.entry.context` | list[str] | no | list() |  | Extra trackers snapshotted at entry. | None. | `context: [regime_5m]` |
| `triggers.entry.max_per_watch` | int | null | no | None |  | Max entries per WATCH episode. | None. | `max_per_watch: 1` |
| `triggers.entry.cooldown` | str | null | no | None |  | Minimum time between entries. | None. | `cooldown: 60s` |
| `triggers.add` | object (AddSpec) | null | no | None |  | Add-to-position rule (typed; ADD is not implemented in the label kernel yet -> MISSING_CAPABILITY). | None. | `add: {when: "...", max_adds: 1}` |
| `triggers.add.when` | str | yes |  |  | Predicate. | None. | `when: "..."` |
| `triggers.add.max_adds` | int | no | 1 |  | Cap. | None. | `max_adds: 1` |
| `triggers.precedence` | list[str] | no | list() |  | Order in which states are tried in one epoch. | None. | `precedence: [WATCH, ARMED]` |
| `triggers.reset_when` | str | null | no | None |  | Graph-level edge events that clear every state (and consume the epoch). | None. | `reset_when: "regime_1m.changed or pullback.new_leg"` |
| `triggers.max_transitions_per_epoch` | int | no | 1 |  | Transition cap per epoch. | None. | `max_transitions_per_epoch: 1` |
| `triggers.sub_epochs` | enum | no | none | 'none', 'tracker_events' | 'none' or 'tracker_events' (evaluate again when a tracker changes inside a bar). | Sub-epochs still only see bars closed at or before T. | `sub_epochs: tracker_events` |
| `features` | object (FeaturesSpec) | no | FeaturesSpec() |  | Columns snapshotted at the epoch. | Never an outcome; the forward-outcome guard rejects outcome-like names. | `features: {instances: [...], metadata: {...}}` |
| `features.host` | enum | no | provider_host | 'provider_host', 'synthetic' | provider_host (the canonical feature bundle) or synthetic (test primitives). | The provider host proves every instance binds to a provider at compile time. | `host: provider_host` |
| `features.columns` | map[str -> str] | no | dict() |  | Synthetic host only: output column -> reference. | None. | `columns: {atr: regime.atr}` |
| `features.instances` | list[object (FeatureInstanceSpec)] | no | list() |  | Canonical feature identities with parameters; `over:` expands a parameter set. | Availability comes from the definition (source_timeframe / update_anchor / snapshot_anchor); the compiler binds, the host snapshots at the epoch. | `instances: [{feature: regime_efficiency, over: {timeframe: [1m, 5m]}, context: prior}]` |
| `features.instances[].feature` | str | yes |  | free keys | Canonical identity from `research cap list features`. | None. | `feature: rolling_giveback_atr` |
| `features.instances[].parameters` | map[str -> Any] | no | dict() | free keys | Explicit parameters (may also be given inline as extra keys). | None. | `parameters: {window: 300s, update_every: 1s}` |
| `features.instances[].over` | map[str -> list[Any]] | no | dict() | free keys | Cartesian set-expansion of parameter values. | None. | `over: {timeframe: [1m, 5m]}` |
| `features.instances[].alias` | str | null | no | None | free keys | Output column alias (not allowed with over). | None. | `alias: eff_1m` |
| `features.metadata` | map[str -> str] | no | dict() |  | Output column -> tracker field / epoch field copied into candidates. | Read at T; never an outcome. | `metadata: {regime_age_seconds: regime_1m.age_s, triggering_1s_ts_init: epoch.T}` |
| `features.derived_inputs` | list[object (DerivedInputSpec)] | no | list() |  | Model scores from a frozen parent study (kind frozen_external_model_score). | The parent freeze and model bytes are pinned by sha256; retraining is prohibited. | `derived_inputs: [{name: model_c_score_at_candidate, kind: frozen_external_model_score, ...}]` |
| `features.derived_inputs[].name` | str | yes |  | free keys | Output column. | None. | `name: model_c_score` |
| `features.derived_inputs[].kind` | str | yes |  | free keys | Registered derived-input kind. | None. | `kind: frozen_external_model_score` |
| `features.bindings` | map[str -> Any] | no | dict() |  | Feature-host input bindings: completed bars, regime transition source, snapshot fields. | Binding names are checked by the compiler against the provider host requirements. | `bindings: {completed_5m: {tracker: regime_bar_5m, ready_gate: false}, snapshot: {atr: regime_1m.atr}}` |
| `outcome` | object (OutcomeSpec) | yes |  |  | How a candidate is labeled from the future path. | The only section allowed to read bars after T. | `outcome: {kind: label, event: regime_1m.flipped, horizon: 180s, direction: regime_1m.dir}` |
| `outcome.kind` | enum | yes |  | 'label', 'trade' | label (LabelOutcomeContract) or trade (TradeExecutionContract; typed only, no sink yet). | Labels read only bars after the entry; candidates never carry outcome columns. | `kind: label` |
| `outcome.entry_reference` | str | no | next_bar_open |  | Where the outcome starts measuring. | Must be executable for a label contract (next_bar_open). | `entry_reference: next_bar_open` |
| `outcome.direction` | str | null | no | None |  | Reference giving the favorable direction (default population.direction). | Read at T. | `direction: regime_1m.dir` |
| `outcome.relation` | enum | no | continuation | 'continuation', 'fade' | continuation (barriers in `direction`) or fade (barriers against it). | Shape C: the sealed authority fades the prevailing regime. | `relation: fade` |
| `outcome.atr` | str | null | no | None |  | Reference for the ATR used to scale barriers, frozen at the decision. | None. | `atr: regime_1m.atr` |
| `outcome.atr_availability` | enum | null | no | None | 'at_decision_delivery', 'through_decision_ts' | at_decision_delivery vs through_decision_ts: whether a coarser bar closing exactly at T is applied before the ATR is frozen. | AMBIGUOUS_TEMPORAL_SEMANTICS if omitted for a barrier contract. | `atr_availability: through_decision_ts` |
| `outcome.horizon` | str | null | no | None |  | Default horizon for arms/items ('300s'). | Measured from the entry instant. | `horizon: 300s` |
| `outcome.session_end` | enum | no | censor | 'censor', 'ignore' | censor: an arm whose horizon passes the session close is CENSORED SESSION_END; ignore: no session censoring. | None. | `session_end: censor` |
| `outcome.session` | str | null | no | None |  | Censoring session (default population.session); use with population.session ALL to censor at RTH close. | None. | `session: RTH` |
| `outcome.max_gap` | str | null | no | None |  | Maximum bar-to-bar gap inside the label window; larger gaps censor GAP. | None. | `max_gap: 60s` |
| `outcome.same_bar_rule` | enum | no | ambiguous_censor | 'ambiguous_censor', 'adverse_first' | ambiguous_censor (favorable and adverse touched in one bar -> CENSORED) or adverse_first. | Same-bar collision precedence must be explicit for trade-like semantics. | `same_bar_rule: ambiguous_censor` |
| `outcome.horizon_end_rule` | enum | no | strict | 'strict', 'first_bar_at_or_after' | strict: no bar closing after the horizon end is evaluated; first_bar_at_or_after: the first bar closing at/after the end is still evaluated for a hit (bounded by the session). | Differs only on sparse seconds; the sealed regime_transition authority uses first_bar_at_or_after. | `horizon_end_rule: strict` |
| `outcome.barrier` | map[str -> Any] | null | no | None |  | Barrier race: {favorable_atr, adverse_atr, horizon?, expiry?} or {arms: [...], primary, expiry}. | Each arm yields <prefix>_label/_disposition/_censor_reason/_resolution_seconds. | `barrier: {primary: tp1_sl1, expiry: censor, arms: [{id: tp1_sl1, favorable_atr: 1.0, adverse_atr: 1.0, prefix: target_tp1_sl1}]}` |
| `outcome.event` | str | null | no | None |  | Event test resolving the label (e.g. regime_1m.flipped, regime_1m.flipped(to=-1)). | Inclusive horizon; a candidate whose horizon ends exactly at the current bar is held one tick. | `event: regime_1m.flipped` |
| `outcome.items` | list[object (OutcomeItemSpec)] | no | list() |  | Named outcome items for compositions. | None. | `items: [{id: tp, kind: barrier, favorable_atr: 1.0, adverse_atr: 0.75}]` |
| `outcome.items[].id` | str | yes |  |  | Item id. | None. | `id: tp` |
| `outcome.items[].kind` | enum | yes |  | 'barrier', 'event', 'horizon', 'stop_move', 'trail' | barrier | event | horizon | stop_move | trail (only barrier/event are implemented in the label kernel). | None. | `kind: barrier` |
| `outcome.items[].favorable_atr` | float | null | no | None |  | Favorable barrier distance in ATR. | None. | `favorable_atr: 1.0` |
| `outcome.items[].adverse_atr` | float | null | no | None |  | Adverse barrier distance in ATR. | None. | `adverse_atr: 0.75` |
| `outcome.items[].when` | str | null | no | None |  | Event predicate for event items. | None. | `when: regime_1m.flipped` |
| `outcome.items[].horizon` | str | null | no | None |  | Item horizon. | None. | `horizon: 300s` |
| `outcome.items[].expiry` | enum | no | censor | 'censor', 'negative' | censor (TIMEOUT) or negative at horizon expiry. | Timeout = negative is a scientific decision; declare it. | `expiry: censor` |
| `outcome.composition` | enum | null | no | None | 'AND', 'OR' | AND / OR over items with monotone worst-status censoring. | AND(False, censored) -> CENSORED; labels only when every child resolved. | `composition: AND` |
| `outcome.precedence` | list[str] | no | list() |  | Order of items when several resolve on the same bar. | None. | `precedence: [tp, sl]` |
| `outcome.fill_model` | object (FillModelSpec) | null | no | None |  | Trade contract fill assumptions (typed only). | None. | `fill_model: {order_type: market}` |
| `outcome.fill_model.order_type` | enum | no | market | 'market', 'limit', 'stop' | market | limit | stop. | None. | `order_type: market` |
| `outcome.fill_model.latency_bars` | int | no | 0 |  | Bars of latency. | None. | `latency_bars: 0` |
| `outcome.fill_model.slippage_ticks` | float | no | 0.0 |  | Slippage. | None. | `slippage_ticks: 0` |
| `outcome.fill_model.spread_ticks` | float | no | 0.0 |  | Spread. | None. | `spread_ticks: 0` |
| `outcome.label_column` | str | null | no | None |  | Name of the primary label column (default target_flip_within_horizon). | None. | `label_column: target_flip_within_horizon` |
| `chronology` | object (ChronologySpec) | yes |  |  | Year roles and warmup. | TRAIN/dev/prohibited are enforced by the controller and preflight. | `chronology: {train: [2021], dev: [2022], prohibited: [2023, 2024, 2025, 2026]}` |
| `chronology.train` | list[int] | yes |  |  | TRAIN years (collection partitions). | The only years a fit or tuning may see. | `train: [2021]` |
| `chronology.dev` | list[int] | no | list() |  | Dev/OOS years, opened only by the oos stage after the TRAIN freeze. | Never read before assert_oos_open. | `dev: [2022]` |
| `chronology.prohibited` | list[int] | no | list() |  | Years no stage may read. | None. | `prohibited: [2023, 2024, 2025, 2026]` |
| `chronology.diagnostic` | list[int] | no | list() |  | Years reserved for diagnostics only. | None. | `diagnostic: []` |
| `chronology.warmup` | object (WarmupSpec) | no | WarmupSpec() |  | Warmup policy before a partition. | Warmup bars feed trackers; no candidates/targets are emitted from warmup unless declared. | `warmup: {days_before_partition: 5}` |
| `chronology.warmup.days_before_partition` | int | no | 5 |  | Calendar days of lead-in bars. | None. | `days_before_partition: 5` |
| `chronology.warmup.candidate_emission` | bool | no | False |  | Emit candidates during warmup. | Normally false. | `candidate_emission: false` |
| `chronology.warmup.target_generation` | bool | no | False |  | Resolve targets during warmup. | Normally false. | `target_generation: false` |
| `chronology.authorized_dates` | list[str] | no | list() |  | Smoke days the controller may run before collection. | None. | `authorized_dates: ['2021-01-05']` |
| `model` | enum | object (ModelSpec) | no | none | 'none' | 'none', a training declaration, or score mode. | None. | `model: none` |
| `model.mode` | enum | no | train | 'train', 'score' | train (fit) or score (reuse frozen models from the store). | Score mode trains nothing. | `mode: score` |
| `model.family` | str | null | no | None |  | Registered driver family without the 'model.' prefix (lightgbm, gradient_boosting, logistic_regression). | None. | `family: lightgbm` |
| `model.params` | map[str -> Any] | no | dict() |  | Hyperparameters (random_state/seed is popped and used as the seed). | None. | `params: {n_estimators: 200, max_depth: 3, random_state: 42}` |
| `model.arms` | list[str] | no | list() |  | Named arms for per-arm models (informational). | None. | `arms: [LONG, SHORT]` |
| `model.validation` | object (ValidationSpec) | null | no | None |  | Year-role table: protocol, tuning years, final validation years, trials, seed, metric. | Tuning years must be inside TRAIN and disjoint from final validation; dev years may never enter. | `validation: {protocol: model_selection.random, tuning_years: [2021, 2022], final_train_validation_years: [2023]}` |
| `model.validation.protocol` | str | yes |  |  | Registered validation protocol (model_selection.random | model_selection.optuna | ...). | None. | `protocol: model_selection.random` |
| `model.validation.tuning_years` | list[int] | no | list() |  | Walk-forward tuning years (fit on earlier, validate on the next). | Two or more needed for a search. | `tuning_years: [2021, 2022]` |
| `model.validation.final_train_validation_years` | list[int] | no | list() |  | Accept/reject years for the already-selected winner (no re-selection). | None. | `final_train_validation_years: [2023]` |
| `model.validation.max_trials` | int | null | no | None |  | Bounded number of unique trials. | None. | `max_trials: 20` |
| `model.validation.random_seed` | int | null | no | None |  | Sampler seed. | None. | `random_seed: 42` |
| `model.validation.primary_metric` | str | null | no | None |  | roc_auc | pr_auc | brier. | None. | `primary_metric: roc_auc` |
| `model.models` | list[object (ScoredModelSpec)] | no | list() |  | Score mode: frozen model ids with label column and row subset. | Scoring happens after collection on merged frames; never inside the host. | `models: [{id: <sha256>, label: target_tp1_sl1_0_label, subset: {regime_direction: 1}, name: LONG_SL1_0}]` |
| `model.models[].id` | str | yes |  |  | Model store id (sha256). | None. | `id: 98ab6190e8df...443a8` |
| `model.models[].label` | str | yes |  |  | Outcome label column to evaluate against. | Must be an outcome column of this study. | `label: target_tp1_sl1_0_label` |
| `model.models[].subset` | map[str -> Any] | no | dict() |  | Explicit column == value row filters. | No hidden direction semantics. | `subset: {regime_direction: 1}` |
| `model.models[].name` | str | null | no | None |  | Display name. | None. | `name: LONG_SL1_0` |
| `model.search_space` | map[str -> Any] | no | dict() |  | param -> [choices] | {low, high, log?, int?}; searched by validation.protocol over walk-forward tuning folds. | TRAIN-only by construction; ledger in artifacts/tuning_trials.json. | `search_space: {n_estimators: [100, 200], learning_rate: {low: 0.01, high: 0.3, log: true}}` |

## Notes

* `streams[0]` is the execution stream unless a `role` is given; every other stream defaults to `context`.
* `model: none` is the default; `model.mode: score` needs `model.models`; `model.mode: train` needs `model.family`.
* `outcome.kind: trade` compiles to a typed TradeExecutionContract but has no sink in this phase; use `kind: label`.
* Typed compile failures (`CapabilityGap`): MISSING_CAPABILITY, INVALID_PARAMETERIZATION, AMBIGUOUS_TEMPORAL_SEMANTICS, UNAVAILABLE_STREAM, UNSUPPORTED_COMPOSITION, SEMANTIC_DECISION_REQUIRED.
* Registry-blind drafts: write `unresolved:<semantic description>` where a capability id would go; the compiler returns MISSING_CAPABILITY with the closest registered ids.
