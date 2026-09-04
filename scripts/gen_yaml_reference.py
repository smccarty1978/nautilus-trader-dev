"""Generate docs/RESEARCH_YAML_REFERENCE.md from the Platform V2 grammar (research_workflow/grammar/spec.py).

Field names, types, requiredness, defaults and allowed values come from the pydantic models; the
scientific meaning / causal implication / example for each field is the curated MEANING table below,
which a test forces to cover every grammar field. Run with --check to verify the committed document
is current (the docs test does this).

    python scripts/gen_yaml_reference.py            # rewrite docs/RESEARCH_YAML_REFERENCE.md
    python scripts/gen_yaml_reference.py --check    # exit 1 if the committed file differs
"""
from __future__ import annotations

import argparse
import sys
import typing
from pathlib import Path
from typing import Any, Dict, List, Tuple, get_args, get_origin

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pydantic import BaseModel  # noqa: E402

from research_workflow.grammar import spec as G  # noqa: E402

OUT = ROOT / "docs" / "RESEARCH_YAML_REFERENCE.md"

# (meaning, causal implication, example) per dotted field path. Keep it short; the grammar is the authority.
MEANING: Dict[str, Tuple[str, str, str]] = {
    "study": ("Identity section.", "None.", "study: {id: my_study, tier: 2, question: \"...\"}"),
    "streams": ("Datasets and timeframes; the first is the execution stream.", "Only external timeframes declared in the DatasetSpec are read from disk; the rest are host-derived complete buckets.", "streams: [{dataset: NQ_1S_V2_GLOBEX, timeframes: [1s, 1m]}]"),
    "population": ("Who is a candidate and when a decision epoch occurs.", "Everything here is evaluated at T from state visible at T.", "population: {session: RTH, cadence: completed_1s, qualify: \"regime_1m.dir != 0\", direction: regime_1m.dir}"),
    "context": ("Named tracker instances (stateful causal state).", "Trackers only see bars closed at or before the epoch.", "context: {regime_1m: {tracker: regime.dual_ema, timeframe: 1m}}"),
    "features": ("Columns snapshotted at the epoch.", "Never an outcome; the forward-outcome guard rejects outcome-like names.", "features: {instances: [...], metadata: {...}}"),
    "outcome": ("How a candidate is labeled from the future path.", "The only section allowed to read bars after T.", "outcome: {kind: label, event: regime_1m.flipped, horizon: 180s, direction: regime_1m.dir}"),
    "chronology": ("Year roles and warmup.", "TRAIN/dev/prohibited are enforced by the controller and preflight.", "chronology: {train: [2021], dev: [2022], prohibited: [2023, 2024, 2025, 2026]}"),
    "study.id": ("Study identifier; also the directory name under studies/.", "None.", "id: v2_shape_a_flip_180s"),
    "study.tier": ("Ceremony tier 1-3 (see CLAUDE.md §7).", "Tier 3 requires repo-scout closure evidence before sealing.", "tier: 2"),
    "study.question": ("The research question in one sentence.", "Audits read it to judge whether the population and outcome answer it.", "question: \"Does causal state at T predict a 1m regime flip within 180s?\""),
    "study.description": ("Free text.", "None.", "description: fresh v2 study"),
    "streams[].dataset": ("Committed DatasetSpec id (research/datasets/<id>.yaml); never a path.", "The plan binds the dataset logical digest; readiness verifies bytes.", "dataset: NQ_1S_V2_GLOBEX"),
    "streams[].instrument": ("Instrument symbol; defaults to the dataset's instrument.", "None.", "instrument: NQ"),
    "streams[].timeframes": ("Timeframes to deliver ('1s', '5s', '1m', '5m'). Only timeframes declared in the DatasetSpec are external; others are host-derived complete buckets.", "Only the finest external timeframe of the execution instrument carries epochs; every coarser external timeframe is a context stream visible strictly before the epoch.", "timeframes: [1s, 1m]"),
    "streams[].role": ("execution (the first stream by default) or context.", "Context bars are queued until an execution bar with a strictly later ts_init arrives.", "role: context"),
    "streams[].same_ts": ("Opt-in to same-timestamp visibility of a context stream.", "'available' is refused with SEMANTIC_DECISION_REQUIRED until a tie-order policy is proven.", "same_ts: unavailable"),
    "population.session": ("Session name from the session table (RTH, ALL, ...).", "Candidates are emitted only inside the session; outcome censoring uses outcome.session when given.", "session: RTH"),
    "population.cadence": ("'completed_1s' | 'completed_1m' | a grid {every, anchor, max_age, index_column}.", "Epochs occur at bar close (ts_init); a grid anchors checkpoints to a tracker field (e.g. regime start).", "cadence: {every: 5s, anchor: regime_1m.start_ns, max_age: 1800s}"),
    "population.cadence.every": ("Grid spacing.", "None.", "every: 5s"),
    "population.cadence.anchor": ("Tracker field the grid counts from.", "Must be known at the epoch.", "anchor: regime_1m.start_ns"),
    "population.cadence.max_age": ("Stop emitting checkpoints past this age.", "None.", "max_age: 1800s"),
    "population.cadence.index_column": ("Output column carrying the checkpoint index.", "None.", "index_column: checkpoint_index"),
    "population.qualify": ("Predicate over tracker fields at the epoch; event tests are not allowed here.", "Only state visible at T; any outcome column in a qualify is impossible by construction.", "qualify: \"regime_1m.age_s >= 120s and excursion.mfe_atr >= 1.0\""),
    "population.direction": ("Reference giving the candidate direction (+1/-1).", "Read at T.", "direction: regime_1m.dir"),
    "population.anchor_identity": ("Reference stamped as regime_start_ns (part of the row key).", "None.", "anchor_identity: regime_1m.start_ns"),
    "context.<name>.tracker": ("Registered tracker capability id without the 'tracker.' prefix; other keys are that tracker's parameters (see `research cap describe tracker.<id>`).", "Trackers update on bar close of their stream and are read at the epoch; their WARMUP_BARS extend the warmup window.", "regime_1m: {tracker: regime.dual_ema, timeframe: 1m}"),
    "context.<name>.instrument": ("Instrument for multi-instrument context.", "Cross-instrument bars are context streams (strictly before the epoch).", "instrument: ES"),
    "triggers": ("'every_candidate' or a trigger graph.", "None.", "triggers: every_candidate"),
    "triggers.cadence": ("Evaluate the graph on 'completed_1s' bars or on 'tracker_events'.", "None.", "cadence: completed_1s"),
    "triggers.states": ("Named states with enter/expire predicates; OBSERVE is implicit.", "Predicates read tracker state and edge events of the current epoch only.", "states: {WATCH: {enter_when: \"pullback.depth_atr >= 1.0\"}}"),
    "triggers.states.<S>.enter_when": ("Predicate to enter the state.", "None.", "enter_when: \"state == WATCH and regime_5s.dir == -regime_1m.dir\""),
    "triggers.states.<S>.expire_when": ("Predicate that leaves the state (back to OBSERVE).", "age(STATE) counts from the entering epoch.", "expire_when: \"age(WATCH) > 600s\""),
    "triggers.states.<S>.from": ("Allowed predecessor states.", "None.", "from: [WATCH]"),
    "triggers.states.<S>.chain": ("May be entered in the same sub-epoch as its predecessor.", "None.", "chain: true"),
    "triggers.entry": ("The entry rule: when, reference price, per-watch limits.", "Entry fires on an edge; the reference is resolved on the NEXT bar (next_bar_open).", "entry: {when: \"state == ARMED and regime_5s.turned(from=-regime_1m.dir, to=regime_1m.dir)\", reference: next_bar_open, max_per_watch: 1}"),
    "triggers.entry.when": ("Entry predicate (usually an edge test).", "None.", "when: \"state == ARMED and x.turned(to=1)\""),
    "triggers.entry.reference": ("Entry reference from research_workflow/entry_references.py.", "Only next_bar_open / next_printed_bar_open are executable; decision_close is a research mark.", "reference: next_bar_open"),
    "triggers.entry.context": ("Extra trackers snapshotted at entry.", "None.", "context: [regime_5m]"),
    "triggers.entry.max_per_watch": ("Max entries per WATCH episode.", "None.", "max_per_watch: 1"),
    "triggers.entry.cooldown": ("Minimum time between entries.", "None.", "cooldown: 60s"),
    "triggers.add": ("Add-to-position rule (typed; ADD is not implemented in the label kernel yet -> MISSING_CAPABILITY).", "None.", "add: {when: \"...\", max_adds: 1}"),
    "triggers.add.when": ("Predicate.", "None.", "when: \"...\""),
    "triggers.add.max_adds": ("Cap.", "None.", "max_adds: 1"),
    "triggers.precedence": ("Order in which states are tried in one epoch.", "None.", "precedence: [WATCH, ARMED]"),
    "triggers.reset_when": ("Graph-level edge events that clear every state (and consume the epoch).", "None.", "reset_when: \"regime_1m.changed or pullback.new_leg\""),
    "triggers.max_transitions_per_epoch": ("Transition cap per epoch.", "None.", "max_transitions_per_epoch: 1"),
    "triggers.sub_epochs": ("'none' or 'tracker_events' (evaluate again when a tracker changes inside a bar).", "Sub-epochs still only see bars closed at or before T.", "sub_epochs: tracker_events"),
    "features.host": ("provider_host (the canonical feature bundle) or synthetic (test primitives).", "The provider host proves every instance binds to a provider at compile time.", "host: provider_host"),
    "features.columns": ("Synthetic host only: output column -> reference.", "None.", "columns: {atr: regime.atr}"),
    "features.instances": ("Canonical feature identities with parameters; `over:` expands a parameter set.", "Availability comes from the definition (source_timeframe / update_anchor / snapshot_anchor); the compiler binds, the host snapshots at the epoch.", "instances: [{feature: regime_efficiency, over: {timeframe: [1m, 5m]}, context: prior}]"),
    "features.instances[].feature": ("Canonical identity from `research cap list features`.", "None.", "feature: rolling_giveback_atr"),
    "features.instances[].parameters": ("Explicit parameters (may also be given inline as extra keys).", "None.", "parameters: {window: 300s, update_every: 1s}"),
    "features.instances[].over": ("Cartesian set-expansion of parameter values.", "None.", "over: {timeframe: [1m, 5m]}"),
    "features.instances[].alias": ("Output column alias (not allowed with over).", "None.", "alias: eff_1m"),
    "features.metadata": ("Output column -> tracker field / epoch field copied into candidates.", "Read at T; never an outcome.", "metadata: {regime_age_seconds: regime_1m.age_s, triggering_1s_ts_init: epoch.T}"),
    "features.derived_inputs": ("Model scores from a frozen parent study (kind frozen_external_model_score).", "The parent freeze and model bytes are pinned by sha256; retraining is prohibited.", "derived_inputs: [{name: model_c_score_at_candidate, kind: frozen_external_model_score, ...}]"),
    "features.derived_inputs[].name": ("Output column.", "None.", "name: model_c_score"),
    "features.derived_inputs[].kind": ("Registered derived-input kind.", "None.", "kind: frozen_external_model_score"),
    "features.bindings": ("Feature-host input bindings: completed bars, regime transition source, snapshot fields.", "Binding names are checked by the compiler against the provider host requirements.", "bindings: {completed_5m: {tracker: regime_bar_5m, ready_gate: false}, snapshot: {atr: regime_1m.atr}}"),
    "outcome.kind": ("label (LabelOutcomeContract) or trade (TradeExecutionContract; typed only, no sink yet).", "Labels read only bars after the entry; candidates never carry outcome columns.", "kind: label"),
    "outcome.entry_reference": ("Where the outcome starts measuring.", "Must be executable for a label contract (next_bar_open).", "entry_reference: next_bar_open"),
    "outcome.direction": ("Reference giving the favorable direction (default population.direction).", "Read at T.", "direction: regime_1m.dir"),
    "outcome.relation": ("continuation (barriers in `direction`) or fade (barriers against it).", "Shape C: the sealed authority fades the prevailing regime.", "relation: fade"),
    "outcome.atr": ("Reference for the ATR used to scale barriers, frozen at the decision.", "None.", "atr: regime_1m.atr"),
    "outcome.atr_availability": ("at_decision_delivery vs through_decision_ts: whether a coarser bar closing exactly at T is applied before the ATR is frozen.", "AMBIGUOUS_TEMPORAL_SEMANTICS if omitted for a barrier contract.", "atr_availability: through_decision_ts"),
    "outcome.horizon": ("Default horizon for arms/items ('300s').", "Measured from the entry instant.", "horizon: 300s"),
    "outcome.session_end": ("censor: an arm whose horizon passes the session close is CENSORED SESSION_END; ignore: no session censoring.", "None.", "session_end: censor"),
    "outcome.session": ("Censoring session (default population.session); use with population.session ALL to censor at RTH close.", "None.", "session: RTH"),
    "outcome.max_gap": ("Maximum bar-to-bar gap inside the label window; larger gaps censor GAP.", "None.", "max_gap: 60s"),
    "outcome.same_bar_rule": ("ambiguous_censor (favorable and adverse touched in one bar -> CENSORED) or adverse_first.", "Same-bar collision precedence must be explicit for trade-like semantics.", "same_bar_rule: ambiguous_censor"),
    "outcome.horizon_end_rule": ("strict: no bar closing after the horizon end is evaluated; first_bar_at_or_after: the first bar closing at/after the end is still evaluated for a hit (bounded by the session).", "Differs only on sparse seconds; the sealed regime_transition authority uses first_bar_at_or_after.", "horizon_end_rule: strict"),
    "outcome.barrier": ("Barrier race: {favorable_atr, adverse_atr, horizon?, expiry?} or {arms: [...], primary, expiry}.", "Each arm yields <prefix>_label/_disposition/_censor_reason/_resolution_seconds.", "barrier: {primary: tp1_sl1, expiry: censor, arms: [{id: tp1_sl1, favorable_atr: 1.0, adverse_atr: 1.0, prefix: target_tp1_sl1}]}"),
    "outcome.event": ("Event test resolving the label (e.g. regime_1m.flipped, regime_1m.flipped(to=-1)).", "Inclusive horizon; a candidate whose horizon ends exactly at the current bar is held one tick.", "event: regime_1m.flipped"),
    "outcome.items": ("Named outcome items for compositions.", "None.", "items: [{id: tp, kind: barrier, favorable_atr: 1.0, adverse_atr: 0.75}]"),
    "outcome.items[].id": ("Item id.", "None.", "id: tp"),
    "outcome.items[].kind": ("barrier | event | horizon | stop_move | trail (only barrier/event are implemented in the label kernel).", "None.", "kind: barrier"),
    "outcome.items[].favorable_atr": ("Favorable barrier distance in ATR.", "None.", "favorable_atr: 1.0"),
    "outcome.items[].adverse_atr": ("Adverse barrier distance in ATR.", "None.", "adverse_atr: 0.75"),
    "outcome.items[].when": ("Event predicate for event items.", "None.", "when: regime_1m.flipped"),
    "outcome.items[].horizon": ("Item horizon.", "None.", "horizon: 300s"),
    "outcome.items[].expiry": ("censor (TIMEOUT) or negative at horizon expiry.", "Timeout = negative is a scientific decision; declare it.", "expiry: censor"),
    "outcome.composition": ("AND / OR over items with monotone worst-status censoring.", "AND(False, censored) -> CENSORED; labels only when every child resolved.", "composition: AND"),
    "outcome.precedence": ("Order of items when several resolve on the same bar.", "None.", "precedence: [tp, sl]"),
    "outcome.fill_model": ("Trade contract fill assumptions (typed only).", "None.", "fill_model: {order_type: market}"),
    "outcome.fill_model.order_type": ("market | limit | stop.", "None.", "order_type: market"),
    "outcome.fill_model.latency_bars": ("Bars of latency.", "None.", "latency_bars: 0"),
    "outcome.fill_model.slippage_ticks": ("Slippage.", "None.", "slippage_ticks: 0"),
    "outcome.fill_model.spread_ticks": ("Spread.", "None.", "spread_ticks: 0"),
    "outcome.label_column": ("Name of the primary label column (default target_flip_within_horizon).", "None.", "label_column: target_flip_within_horizon"),
    "chronology.train": ("TRAIN years (collection partitions).", "The only years a fit or tuning may see.", "train: [2021]"),
    "chronology.dev": ("Dev/OOS years, opened only by the oos stage after the TRAIN freeze.", "Never read before assert_oos_open.", "dev: [2022]"),
    "chronology.prohibited": ("Years no stage may read.", "None.", "prohibited: [2023, 2024, 2025, 2026]"),
    "chronology.diagnostic": ("Years reserved for diagnostics only.", "None.", "diagnostic: []"),
    "chronology.warmup": ("Warmup policy before a partition.", "Warmup bars feed trackers; no candidates/targets are emitted from warmup unless declared.", "warmup: {days_before_partition: 5}"),
    "chronology.warmup.days_before_partition": ("Calendar days of lead-in bars.", "None.", "days_before_partition: 5"),
    "chronology.warmup.candidate_emission": ("Emit candidates during warmup.", "Normally false.", "candidate_emission: false"),
    "chronology.warmup.target_generation": ("Resolve targets during warmup.", "Normally false.", "target_generation: false"),
    "chronology.authorized_dates": ("Smoke days the controller may run before collection.", "None.", "authorized_dates: ['2021-01-05']"),
    "model": ("'none', a training declaration, or score mode.", "None.", "model: none"),
    "model.mode": ("train (fit) or score (reuse frozen models from the store).", "Score mode trains nothing.", "mode: score"),
    "model.family": ("Registered driver family without the 'model.' prefix (lightgbm, gradient_boosting, logistic_regression).", "None.", "family: lightgbm"),
    "model.params": ("Hyperparameters (random_state/seed is popped and used as the seed).", "None.", "params: {n_estimators: 200, max_depth: 3, random_state: 42}"),
    "model.arms": ("Named arms for per-arm models (informational).", "None.", "arms: [LONG, SHORT]"),
    "model.validation": ("Year-role table: protocol, tuning years, final validation years, trials, seed, metric.", "Tuning years must be inside TRAIN and disjoint from final validation; dev years may never enter.", "validation: {protocol: model_selection.random, tuning_years: [2021, 2022], final_train_validation_years: [2023]}"),
    "model.validation.protocol": ("Registered validation protocol (model_selection.random | model_selection.optuna | ...).", "None.", "protocol: model_selection.random"),
    "model.validation.tuning_years": ("Walk-forward tuning years (fit on earlier, validate on the next).", "Two or more needed for a search.", "tuning_years: [2021, 2022]"),
    "model.validation.final_train_validation_years": ("Accept/reject years for the already-selected winner (no re-selection).", "None.", "final_train_validation_years: [2023]"),
    "model.validation.max_trials": ("Bounded number of unique trials.", "None.", "max_trials: 20"),
    "model.validation.random_seed": ("Sampler seed.", "None.", "random_seed: 42"),
    "model.validation.primary_metric": ("roc_auc | pr_auc | brier.", "None.", "primary_metric: roc_auc"),
    "model.models": ("Score mode: frozen model ids with label column and row subset.", "Scoring happens after collection on merged frames; never inside the host.", "models: [{id: <sha256>, label: target_tp1_sl1_0_label, subset: {regime_direction: 1}, name: LONG_SL1_0}]"),
    "model.models[].id": ("Model store id (sha256).", "None.", "id: 98ab6190e8df...443a8"),
    "model.models[].label": ("Outcome label column to evaluate against.", "Must be an outcome column of this study.", "label: target_tp1_sl1_0_label"),
    "model.models[].subset": ("Explicit column == value row filters.", "No hidden direction semantics.", "subset: {regime_direction: 1}"),
    "model.models[].name": ("Display name.", "None.", "name: LONG_SL1_0"),
    "model.models[].expect": ("Optional identity expectations, authenticated against the model-store lineage before scoring.", "A mismatch refuses the model (MODEL_EXPECTATION_MISMATCH).", "expect: {target_arm: SL1_0}"),
    "model.models[].expect.study_id": ("Expected lineage.study_id.", "None.", "study_id: parent_study"),
    "model.models[].expect.target_arm": ("Expected lineage.target_arm.", "None.", "target_arm: SL1_0"),
    "model.models[].expect.direction": ("Expected lineage.direction.", "None.", "direction: LONG"),
    "model.models[].expect.cell_id": ("Expected lineage.cell_id.", "None.", "cell_id: LONG_SL1_0"),
    "model.models[].expect.canonical_sha256": ("Expected manifest canonical.byte_sha256 -- binds to the estimator's actual bytes, not only lineage; catches a substituted estimator that refreshes its own canonical/golden bytes under an unchanged model_id.",
                                               "A wrong or stale declared value fails closed as CANONICAL_SHA_MISMATCH before score().",
                                               "canonical_sha256: 3b1c...a2"),
    "model.search_space": ("param -> [choices] | {low, high, log?, int?}; searched by validation.protocol over walk-forward tuning folds.", "TRAIN-only by construction; ledger in artifacts/tuning_trials.json.", "search_space: {n_estimators: [100, 200], learning_rate: {low: 0.01, high: 0.3, log: true}}"),
}


def _type_name(tp: Any) -> str:
    origin = get_origin(tp)
    if origin is typing.Literal:
        return "enum"
    if origin is typing.Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        return " | ".join(_type_name(a) for a in args) + (" | null" if len(args) < len(get_args(tp)) else "")
    if origin in (list, List):
        return f"list[{_type_name(get_args(tp)[0])}]" if get_args(tp) else "list"
    if origin in (dict, Dict):
        a = get_args(tp)
        return f"map[{_type_name(a[0])} -> {_type_name(a[1])}]" if a else "map"
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return f"object ({tp.__name__})"
    return getattr(tp, "__name__", str(tp))


def _literals(tp: Any) -> List[str]:
    origin = get_origin(tp)
    if origin is typing.Literal:
        return [repr(a) for a in get_args(tp)]
    if origin is typing.Union:
        out: List[str] = []
        for a in get_args(tp):
            out += _literals(a)
        return out
    return []


def _submodels(tp: Any) -> List[type]:
    origin = get_origin(tp)
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return [tp]
    out: List[type] = []
    for a in get_args(tp) if origin else ():
        out += _submodels(a)
    return out


def walk(model: type, prefix: str, rows: List[Dict[str, Any]], seen: set) -> None:
    for name, field in model.model_fields.items():
        alias = field.alias or name
        path = f"{prefix}{alias}"
        tp = field.annotation
        default = "required" if field.is_required() else (field.default if field.default_factory is None else f"{field.default_factory.__name__}()")
        rows.append({"path": path, "type": _type_name(tp), "required": field.is_required(), "default": default, "allowed": _literals(tp),
                     "extra_allowed": getattr(model.model_config, "get", lambda k, d=None: d)("extra") == "allow"})
        for sub in _submodels(tp):
            origin = get_origin(tp)
            suffix = "[]." if origin in (list, List) else (".<name>." if origin in (dict, Dict) else ".")
            key = (sub, path)
            if key in seen:
                continue
            seen.add(key)
            walk(sub, f"{path}{suffix}", rows, seen)


def render() -> str:
    rows: List[Dict[str, Any]] = []
    walk(G.StudySpecV2, "", rows, set())
    # normalise paths to the MEANING keys
    def norm(p: str) -> str:
        p = p.replace("population.cadence.", "population.cadence.").replace("triggers.states.<name>.", "triggers.states.<S>.")
        return p
    lines = ["# Platform V2 research YAML reference", "",
             "Generated from `research_workflow/grammar/spec.py` by `scripts/gen_yaml_reference.py` -- do not hand-edit.",
             "The grammar is the authority; the compiler (`research study compile`) is the only validator. Every section is strict:",
             "unknown keys are rejected except where noted (`context.<name>` and `features.instances[]` accept free parameters).", "",
             "Duration strings: `'600s'`, `'5m'`, `'1h'`. References: `tracker.field`, `epoch.T`, `state`, `age(STATE)`.",
             "Predicate language: comparisons, `and/or/not`, `in [..]`, event tests `x.flipped(to=-1)`, `x.changed`, `x.turned(from=, to=)`, `x.new_leg`, `x.terminated`; no arithmetic.", "",
             "| Field | Type | Required | Default | Allowed | Meaning | Causal implication | Example |", "|---|---|---|---|---|---|---|---|"]
    missing = []
    for r in rows:
        key = norm(r["path"])
        m = MEANING.get(key)
        if m is None:
            missing.append(key)
            m = ("(undocumented)", "", "")
        allowed = ", ".join(r["allowed"]) if r["allowed"] else ("free keys" if r["extra_allowed"] else "")
        default = "" if r["required"] else str(r["default"]).replace("|", "\\|")
        lines.append(f"| `{r['path']}` | {r['type']} | {'yes' if r['required'] else 'no'} | {default} | {allowed} | {m[0]} | {m[1]} | `{m[2]}` |")
    lines += ["", "## Notes", "",
              "* `streams[0]` is the execution stream unless a `role` is given; every other stream defaults to `context`.",
              "* `model: none` is the default; `model.mode: score` needs `model.models`; `model.mode: train` needs `model.family`.",
              "* `outcome.kind: trade` compiles to a typed TradeExecutionContract but has no sink in this phase; use `kind: label`.",
              "* Typed compile failures (`CapabilityGap`): MISSING_CAPABILITY, INVALID_PARAMETERIZATION, AMBIGUOUS_TEMPORAL_SEMANTICS, UNAVAILABLE_STREAM, UNSUPPORTED_COMPOSITION, SEMANTIC_DECISION_REQUIRED.",
              "* Registry-blind drafts: write `unresolved:<semantic description>` where a capability id would go; the compiler returns MISSING_CAPABILITY with the closest registered ids.",
              "* Outcome resolution precedence at every bar (in-horizon, or the first post-horizon bar under `horizon_end_rule: first_bar_at_or_after`) is fixed and non-configurable: `SESSION_END > GAP > BARRIER_TOUCH > HORIZON_EXPIRY`. A bar past `outcome.session` close is CENSORED `SESSION_END` before gap or touch are ever evaluated; a bar farther than `outcome.max_gap` from the last accepted bar is CENSORED `GAP` before a barrier touch on that bar is accepted; only then is a favorable/adverse touch resolved; only if none of the above applies and the horizon has elapsed does `expiry` (censor vs negative) apply. This holds identically for the kernel (`research_workflow/host/outcomes.py`) and the independent replay oracle (`research_workflow/target_replay_oracle.py`); it is compiled into every outcome contract as `outcome.semantics.resolution_precedence`.",
              "* DatasetSpec `reference_tables` / `reference_digest` (declared on the dataset YAML under `research/datasets/<id>.yaml`, not on the study grammar): `reference_tables` names which reference tables (sessions, holidays, maintenance, rolls, gaps, out_of_calendar) the dataset carries; `reference_digest` pins their combined content hash. Verification is fail-closed: a hash mismatch at load time refuses the study rather than silently reading a drifted table. A `sessions` table selects the calendar session kind for outcome/population censoring; ETH is `(open, 08:30 CT]` pre-open plus `(15:15 CT or halt end, day close]` post-close -- legacy ETH censoring without a `sessions` reference table is refused (`SEMANTIC_DECISION_REQUIRED`).", ""]
    text = "\n".join(lines)
    if missing:
        raise SystemExit(f"MEANING table is missing entries for: {missing}")
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ns = ap.parse_args()
    text = render()
    if ns.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current.strip() != text.strip():
            print("RESEARCH_YAML_REFERENCE_STALE: run python scripts/gen_yaml_reference.py")
            return 1
        print("RESEARCH_YAML_REFERENCE_CURRENT")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
