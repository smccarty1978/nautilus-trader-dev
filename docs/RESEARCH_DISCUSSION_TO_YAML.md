# From a research discussion to a Platform V2 spec

You have a research conversation with any chat model (ChatGPT, Claude, Gemini, ...). At the end you paste
ONE prompt and get back a Platform V2 `study.yaml` draft plus the list of decisions still open. The draft
then goes through `python scripts/research.py study compile`, which either produces a compiled plan or a
typed `CapabilityGap` you resolve with the registry. Nothing in this flow requires the chat model to see the
repository.

## COPY THIS INTO ANY AI CHAT

The standalone prompt is `research_workflow/templates/research_discussion_to_yaml_prompt.md`. It is
reproduced here verbatim so this page is self-contained.

<!-- PROMPT_START -->
```text
You are a research-specification editor for my Platform V2 quantitative research system (NautilusTrader-based,
causal streaming replay, one declarative `study.yaml` per study, zero study Python).

Using ONLY the research discussion in this conversation plus any capability registry information I paste
(output of `research cap search` / `research cap describe`, or a registry excerpt), convert our agreed research
design into a Platform V2 research specification.

Do not invent scientific assumptions. Do not invent repository capability IDs.

Separate three things everywhere: CONFIRMED BY USER, INFERRED (reasonable non-scientific default, say so), and
UNRESOLVED (a material scientific decision we did not settle). If a material semantic point is unresolved,
preserve it as unresolved rather than guessing.

Extract, in this order: research question; hypothesis; prediction direction; instrument(s); execution
instrument; context instrument(s); session; population; eligibility rules; decision epoch; cadence;
features/context; trackers; trigger sequence; entry/reference price; target/outcome; horizons; barriers;
censoring; collision precedence; horizon-end semantics; chronology; TRAIN years; validation folds; OOS policy;
model family; baseline model; tuning policy; evaluation metrics; economic diagnostics; required artifacts;
parity/reference requirements; assumptions; unresolved semantics; prohibited data.

Points that are UNRESOLVED unless we discussed them explicitly: same-bar TP+SL collision; horizon anchoring and
the horizon-end rule; session-close precedence; missing-data/gap policy; the exact entry reference; same-timestamp
cross-market availability; timeout = negative vs censor; the model-selection metric; which OOS year is authorized.

The final response must contain exactly these sections:

1. EXECUTIVE RESEARCH CONTRACT — one paragraph per extracted item, each tagged CONFIRMED / INFERRED / UNRESOLVED.
2. UNRESOLVED DECISIONS — a numbered list of the scientific decisions still open, each with the options.
3. PLATFORM V2 YAML — one `study.yaml` in the grammar below.
4. CAPABILITIES NEEDED — every tracker / feature / outcome primitive the YAML uses; for each say whether it is a
   registry id I gave you (exact id) or an `unresolved:` semantic binding.
5. VALIDATION PLAN — chronology table (one row per year: TRAIN / tuning / final validation / dev-OOS / prohibited),
   folds, metric, what would falsify the hypothesis.
6. PROHIBITED / LOCKED DATA — years and datasets that must not be read, and by which stage they may be opened.

Before emitting the YAML, verify internally that: every feature is available at the decision epoch; future-path
data appears only in `outcome`; TRAIN and OOS years are disjoint and prohibited years are listed; timeout/censor
semantics are explicit (`expiry`, `session_end`); the entry reference is explicit (`entry_reference`); the horizon
anchor/end rule is explicit (`horizon_end_rule`); same-bar collision precedence is explicit (`same_bar_rule`);
session and gap behaviour are explicit (`session`, `max_gap`); model tuning uses TRAIN tuning years only
(`validation.tuning_years`), never dev years.

Grammar you must use (Platform V2 study.yaml) -- top-level sections: study, streams, context, population, triggers,
features, outcome, chronology, model. Unknown keys are rejected by the compiler; do not add fields not listed:

study: {id: <snake_case>, tier: 2, question: "<one sentence>"}
streams:
  - {dataset: <DatasetSpec id, e.g. NQ_1S_V2_GLOBEX>, timeframes: [1s, 1m]}       # first stream = execution; more streams = context
context:
  <name>: {tracker: <registry id without "tracker.">, <tracker params>}   # e.g. regime.dual_ema, timeframe: 1m
population:
  session: RTH | ALL
  cadence: completed_1s | completed_1m | {every: 5s, anchor: <tracker.field>, max_age: 1800s}
  qualify: "<predicate over tracker fields at T>"      # no event tests here
  direction: <tracker.dir>
  anchor_identity: <tracker.start_ns>
triggers: every_candidate
# or a graph:
#   triggers: {reset_when: "<edge events>", states: {WATCH: {enter_when: "...", expire_when: "age(WATCH) > 600s"},
#              ARMED: {enter_when: "state == WATCH and ...", from: [WATCH], chain: true}},
#              entry: {when: "state == ARMED and <x>.turned(from=..., to=...)", reference: next_bar_open, max_per_watch: 1},
#              precedence: [WATCH, ARMED], sub_epochs: none | tracker_events}
features:
  instances:
    - {feature: <canonical feature name>, <parameters...>}                # e.g. regime_efficiency, timeframe: 1m, context: prior
    - {feature: <name>, over: {timeframe: [1m, 5m]}}                      # set-expansion
  metadata: {<column>: <tracker.field>, triggering_1s_ts_init: epoch.T}
outcome:
  kind: label
  entry_reference: next_bar_open
  direction: <tracker.dir>
  relation: continuation | fade
  atr: <tracker.atr>
  atr_availability: at_decision_delivery | through_decision_ts
  horizon: 300s
  horizon_end_rule: strict | first_bar_at_or_after
  same_bar_rule: ambiguous_censor | adverse_first
  session_end: censor | ignore
  session: RTH
  max_gap: 60s
  barrier: {favorable_atr: 1.0, adverse_atr: 1.0, expiry: censor | negative}
  # or arms: barrier: {primary: <arm id>, expiry: censor, arms: [{id: ..., favorable_atr: ..., adverse_atr: ..., prefix: ...}]}
  # or an event label: event: <tracker>.flipped   (with horizon)
chronology: {train: [<years>], dev: [<year>], prohibited: [<years>], authorized_dates: ['YYYY-MM-DD']}
model: none
# or: model: {family: lightgbm, params: {...}, validation: {protocol: model_selection.random, tuning_years: [...],
#             final_train_validation_years: [], max_trials: 24, random_seed: 42, primary_metric: roc_auc}, search_space: {...}}
# or: model: {mode: score, models: [{id: <sha256>, label: <label column>, subset: {regime_direction: 1}, name: ...}]}

Predicate language: comparisons, and / or / not, durations like 120s, references tracker.field, age(STATE), state,
event tests x.flipped(to=-1), x.changed, x.turned(from=, to=), x.new_leg, x.terminated, membership x in [A, B].
No arithmetic, no other function calls.

Binding rules:
* MODE A (I pasted registry information): use those exact ids and parameters; nothing else.
* MODE B (no registry information): write "unresolved: <semantic requirement>" wherever a tracker or feature id
  would go, e.g. {tracker: "unresolved: rolling 60s volume imbalance from 1s bars", bars: 1s}. The compiler turns
  every unresolved binding into a typed MISSING_CAPABILITY gap with the closest registered ids. Never fabricate an id.
```
<!-- PROMPT_END -->

## Two modes

**MODE A — registry-aware.** Before the final prompt, paste the relevant registry output into the chat:

```bash
python scripts/research.py cap search regime
python scripts/research.py cap describe tracker.regime.dual_ema
python scripts/research.py cap describe regime_efficiency
```

The chat model may then emit exact ids and parameters, and the draft usually compiles first time.

**MODE B — registry-blind.** The chat model knows the semantics but not the ids. It writes
`unresolved: <semantic requirement>` where an id would go. `docs/examples/registry_blind_draft.yaml` is
such a draft; compiling it returns MISSING_CAPABILITY gaps with the closest registered ids:

```bash
python scripts/research.py study compile --study studies/<id>
# -> STATUS: FAIL, gaps: [{kind: MISSING_CAPABILITY, where: context.imbalance, closest: [...]}, ...]
python scripts/research.py cap search imbalance          # resolve each gap, edit the YAML, recompile
```

If no registered primitive matches, the gap becomes a capability proposal (`WORKFLOW.md` §E).

## What the study owner does with the response

1. Copy section 3 into `studies/<id>/study.yaml` (after `research study new <id>`).
2. Resolve section 2 (UNRESOLVED DECISIONS) explicitly in the YAML; the compiler refuses to guess
   (`AMBIGUOUS_TEMPORAL_SEMANTICS` / `SEMANTIC_DECISION_REQUIRED`).
3. Compile; resolve gaps with the registry.
4. Keep sections 1, 5 and 6 as `studies/<id>/research_decision.yaml` / `SPEC.md` content: the auditors
   compare the compiled plan against them.

## Compile-tested references

`docs/examples/checkpoint_classifier.yaml`, `docs/examples/watch_trigger.yaml`,
`docs/examples/multi_arm_outcome.yaml`, `docs/examples/ml_tuning.yaml` compile in
`research_workflow/tests/test_docs_v2.py`; `docs/examples/registry_blind_draft.yaml` is an illustrative
draft that must return typed gaps. The full field reference is `docs/RESEARCH_YAML_REFERENCE.md`.
