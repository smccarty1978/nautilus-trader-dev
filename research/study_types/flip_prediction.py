"""Flip Prediction Canonical Study Compiler.
===========================================
Compiles symmetric regime flip prediction studies into authoritative contracts.
"""

from __future__ import annotations

from typing import Any, Dict, List
from research.schemas.study_spec import StudySpec
from research.study_types.base import BaseStudyCompiler, CompileResult, FitDecision
from research.engines.population_engine import compile_population_contract
from research.engines.target_engine import compile_target_contract
from research.engines.feature_binding_engine import compile_feature_contract
from research.engines.timestamp_engine import compile_timestamp_contract
from research.engines.lineage_engine import validate_lineage
from research.engines.baseline_engine import validate_baseline
from research.engines.deliverables_engine import compile_deliverables_contract, modes_for_operation


class FlipPredictionCompiler(BaseStudyCompiler):
    """Compiler for canonical flip_prediction studies."""

    DEFAULT_STRATEGY = "research_workflow.generic_collector.GenericStudyCollector"

    def evaluate_fit(self, spec: StudySpec) -> FitDecision:
        if spec.study.type != "flip_prediction":
            return FitDecision.BESPOKE_REQUIRED

        # Population and target checks
        if spec.population.type != "regime_state":
            return FitDecision.BESPOKE_REQUIRED
        if spec.target.type == "flip":
            pass
        elif spec.target.type == "composite":
            # A composite target is still canonically a flip prediction when a flip
            # event is one of its conditions -- the excursion/return conditions refine
            # what counts as a "clean" flip, they do not change what is being predicted.
            # A composite target with NO flip condition (e.g. pure excursion/return) is
            # not a flip prediction and genuinely needs bespoke.
            conditions = spec.target.conditions or []
            has_flip = any(c.kind == "flip" for c in conditions)
            # An emitted regime-state episode is itself the completed flip-back decision.
            # Its declared *future* ordered barrier is therefore a canonical flip outcome,
            # not an arbitrary non-flip composite. Keep this exception intentionally narrow.
            episode_barrier = (
                bool(spec.population.episode_lifecycle)
                and spec.population.episode_lifecycle.required_event.source == "generic_completed_5s_regime_state"
                and spec.population.episode_lifecycle.emit_condition.source == "generic_completed_5s_regime_state"
                and spec.population.episode_lifecycle.required_event.bar_state == "completed"
                and spec.population.episode_lifecycle.emit_condition.bar_state == "completed"
                and spec.population.episode_lifecycle.required_event.availability_timestamp == "completed_source_bar_ts_init"
                and spec.population.episode_lifecycle.emit_condition.availability_timestamp == "completed_source_bar_ts_init"
                and bool(conditions)
                and all(c.kind == "ordered_barrier" for c in conditions)
                and all(getattr(c, "forward_outcome_id", None) for c in conditions)
            )
            if not has_flip and not episode_barrier:
                return FitDecision.BESPOKE_REQUIRED
        else:
            return FitDecision.BESPOKE_REQUIRED

        # Research operation check: only train_evaluate and artifact_reconstruction are canonical flip_prediction
        allowed_operations = {"train_evaluate", "artifact_reconstruction", "diagnostic_followup"}
        if spec.operation.kind not in allowed_operations:
            return FitDecision.BESPOKE_REQUIRED

        return FitDecision.STUDY_TYPE_MATCH

    def compile(self, spec: StudySpec) -> CompileResult:
        fit = self.evaluate_fit(spec)
        if fit != FitDecision.STUDY_TYPE_MATCH:
            raise ValueError(
                f"STUDY_TYPE_MISMATCH: Canonical 'flip_prediction' cannot express operation "
                f"'{spec.operation.kind}' (allowed: train_evaluate, artifact_reconstruction). "
                f"Use study.type='bespoke' with mandatory 'bespoke.reason' justification."
            )
        spec_hash = spec.compute_sha256()

        # 1. Compile sub-contracts
        pop_contract = compile_population_contract(spec.population, spec.instrument)
        target_contract = compile_target_contract(spec.target)
        feat_contract = compile_feature_contract(spec.features)
        ts_contract = compile_timestamp_contract(spec.instrument.symbol)
        lineage_info = validate_lineage(spec)
        baseline_info = validate_baseline(spec.baseline)

        # 2. Execution contract
        strategy_class = spec.execution.strategy_class or self.DEFAULT_STRATEGY
        exec_contract = {
            "runtime": "nautilustrader",
            "strategy_class": strategy_class,
            "bounded_execution": spec.execution.bounded,
            "progress_seconds": spec.execution.progress_seconds,
            "checkpoint": spec.execution.checkpoint,
            "chronology": {
                "train": spec.chronology.train or [],
                "dev": spec.chronology.dev or [],
                "diagnostic": spec.chronology.diagnostic or [],
                "prohibited": spec.chronology.prohibited or [],
            },
        }

        # Deliverables are mode-partitioned and machine-readable so the contract-checker
        # consumes an authority instead of assembling its own checklist (F1).
        deliverables_contract = compile_deliverables_contract(
            modes=modes_for_operation(spec.operation.kind)
        )

        contracts = {
            "population_contract": pop_contract,
            "target_contract": target_contract,
            "feature_contract": feat_contract,
            "execution_contract": exec_contract,
            "timestamp_contract": ts_contract,
            "deliverables_contract": deliverables_contract,
            "lineage": lineage_info,
            "baseline": baseline_info,
            # Additive, generic capabilities -- absent/empty when a study declares none
            # of them, so an unmodified study's compiled contract keys are unchanged
            # in kind (feat_contract already always carries "derived_causal_inputs";
            # these two are new top-level keys since they have no natural home in an
            # existing per-section contract).
            "required_gates": [g.model_dump() for g in (spec.required_gates or [])],
            "model_selection": spec.model.selection.model_dump() if (spec.model and spec.model.selection) else None,
        }
        if spec.operation.kind == "diagnostic_followup":
            diag = dict(spec.diagnostic_followup or {})
            thresholds = diag.get("thresholds") or {}
            bindings = diag.get("score_columns") or {}
            if set(thresholds) != {"LONG", "SHORT"} or set(bindings) != {"LONG", "SHORT"}:
                raise ValueError("DIAGNOSTIC_FOLLOWUP_BINDING_MISSING")
            names = {d.name for d in ((spec.features.derived_inputs if spec.features else None) or [])}
            if not set(bindings.values()).issubset(names):
                raise ValueError("DIAGNOSTIC_FOLLOWUP_SCORER_NOT_DECLARED")
            contracts["diagnostic_followup"] = diag

        # 3. Render SPEC.md
        spec_md = self._render_spec_md(spec, spec_hash, contracts)

        # 4. Render TASK_PACKET.json
        task_packet = self._render_task_packet(spec, spec_hash, contracts)

        # 5. Derived test definitions
        test_declarations = self._build_test_declarations(spec, contracts)

        # 6. Summary card
        summary_card = self._build_summary_card(spec, fit, contracts)

        return CompileResult(
            fit_decision=fit,
            study_id=spec.study.id,
            study_type=spec.study.type,
            spec_sha256=spec_hash,
            contracts=contracts,
            nt_strategy_class=strategy_class,
            test_declarations=test_declarations,
            rendered_spec_md=spec_md,
            rendered_task_packet=task_packet,
            summary_card=summary_card,
            custom_code_allowed=False,
        )

    def _render_spec_md(self, spec: StudySpec, spec_hash: str, contracts: Dict[str, Any]) -> str:
        pop = spec.population
        target = spec.target
        feat = contracts["feature_contract"]
        chrono = spec.chronology

        deliv = contracts["deliverables_contract"]
        authorized_modes = ", ".join(f"`{m}`" for m in deliv["authorized_modes"])
        lines = []
        for mode, artifacts in deliv["deliverables_by_mode"].items():
            lines.append(f"### Mode `{mode}`")
            lines.append("")
            for a in artifacts:
                meta = deliv["artifact_metadata"][a]
                lines.append(f"- `{a}` -- written to `{meta['relative_to']}` by `{meta['producer']}`")
            lines.append("")
        deliverables_section = "\n".join(lines).rstrip()

        derived_inputs = contracts["feature_contract"].get("derived_causal_inputs") or []
        if derived_inputs:
            di_lines = "\n".join(
                f"- `{d['name']}` <- `{d['parent_study_id']}` "
                f"(`{d['parent_train_freeze_artifact']}`, availability=`{d['availability_reference']}`)"
                for d in derived_inputs
            )
            derived_inputs_section = f"\n## Derived Causal Inputs\n\n{di_lines}\n"
        else:
            derived_inputs_section = ""

        required_gates = contracts.get("required_gates") or []
        if required_gates:
            gate_lines = "\n".join(
                f"- `{g['id']}` (stage=`{g['stage']}`, artifact=`{g['artifact_path']}`)"
                for g in required_gates
            )
            gates_section = f"\n## Required Pre-Freeze Gates\n\n{gate_lines}\n"
        else:
            gates_section = ""

        return f"""# SPEC: {spec.study.id}

**Generated by Study Factory (Canonical {spec.study.type})**  
**Source `study.yaml` SHA-256:** `{spec_hash}`  
**Risk Tier:** `{spec.study.risk_tier}`  
**Execution Runtime:** `NautilusTrader` (`{contracts['execution_contract']['strategy_class']}`)

---

## 1. Executive Summary & Objective

{spec.study.description}

- **Instrument:** `{spec.instrument.symbol}` on `{spec.instrument.venue}`
- **Prevailing Population:** `{pop.prevailing_regime}` ({pop.session} session)
- **Target Event:** `{target.event or 'regime_flip'}` ({target.direction} within {target.horizon_seconds}s)
- **Feature Set:** `{feat.get('source_key', 'custom')}` ({feat.get('feature_count', 0)} features, hash `{feat.get('feature_list_sha256')}`)

---

## 2. Chronology & Partitioning

- **Training Years:** `{chrono.train or []}`
- **Development/Validation Years:** `{chrono.dev or []}`
- **Diagnostic Years:** `{chrono.diagnostic or []}`
- **Prohibited Out-of-Scope Years:** `{chrono.prohibited or []}`

---

## 3. Causal Timing & Timestamp Invariant

- **Raw Databento Semantic:** `OPEN_STAMPED` (`ts_event`)
- **NautilusTrader Event Dispatch:** `CLOSE_STAMPED` (`ts_init = ts_event + duration_ns`)
- **Causal Rule:** `FULL_BAR_OHLCV_AVAILABLE_ONLY_AT_INTERVAL_CLOSE`
- **Latest Source Availability:** `latest_source_availability_ts <= observation_ts`

---

## 4. Deliverables Manifest & Acceptance

Authoritative source: `config/deliverables_contract.json`. This section is **rendered
from** that contract, never hand-listed. The contract-checker consumes the JSON, not this
prose, so the two cannot drift and the checker cannot substitute a scope of its own.

Deliverables are partitioned by mode: a mode is only accountable for artifacts it can
actually produce, and an artifact belonging to a mode this study is not authorized to run
is out of scope rather than missing.

**Authorized modes:** {authorized_modes}

{deliverables_section}
{derived_inputs_section}{gates_section}"""

    def _render_task_packet(self, spec: StudySpec, spec_hash: str, contracts: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "task_packet_version": "1.0",
            "study_id": spec.study.id,
            "study_type": spec.study.type,
            "spec_sha256": spec_hash,
            "risk_tier": spec.study.risk_tier,
            "runtime": "nautilustrader",
            "strategy_class": contracts["execution_contract"]["strategy_class"],
            "contracts": contracts,
            "preflight_required": True,
            "preflight_status": "PENDING_EXECUTION",
        }

    def _build_test_declarations(self, spec: StudySpec, contracts: Dict[str, Any]) -> List[Dict[str, Any]]:
        feat_c = contracts["feature_contract"]
        feat_hash = feat_c.get("feature_list_sha256") or feat_c.get("candidate_universe_hash")
        feat_cnt = feat_c.get("feature_count") or feat_c.get("candidate_universe_count", 0)
        return [
            {
                "name": "test_authorized_chronology_contract",
                "authorized_train": spec.chronology.train or [],
                "authorized_dev": spec.chronology.dev or [],
                "prohibited": spec.chronology.prohibited or [],
            },
            {
                "name": "test_feature_registry_binding",
                "feature_count": feat_cnt,
                "feature_list_sha256": feat_hash,
            },
            {
                "name": "test_population_target_directionality",
                "prevailing_regime": spec.population.prevailing_regime,
                "target_direction": spec.target.direction,
            },
            {
                "name": "test_nautilustrader_runtime_invariant",
                "runtime": "nautilustrader",
            },
        ]

    def _build_summary_card(self, spec: StudySpec, fit: FitDecision, contracts: Dict[str, Any]) -> str:
        feat = contracts["feature_contract"]
        chrono = spec.chronology
        feat_key = feat.get("source_key") or feat.get("source_universe", "custom")
        feat_count = feat.get("feature_count") or feat.get("candidate_universe_count", 0)
        feat_hash = feat.get("feature_list_sha256") or feat.get("candidate_universe_hash", "None")
        return f"""======================================================================
STUDY COMPILED: {spec.study.id}
======================================================================
Type: {spec.study.type}
Fit: {fit.value}
Operation: {spec.operation.kind}
Runtime: NautilusTrader
Strategy: {contracts['execution_contract']['strategy_class']}

Instrument: {spec.instrument.symbol} ({spec.instrument.venue})
Population: {spec.population.prevailing_regime} {spec.population.session}
Target: {spec.target.direction} flip <={spec.target.horizon_seconds}s

Features:
  key: {feat_key}
  count: {feat_count}
  hash: {feat_hash}

Chronology:
  train: {chrono.train}
  dev: {chrono.dev}
  prohibited: {chrono.prohibited}

Custom study code:
  NONE (Canonical NT Strategy Binding)

Preflight eligibility:
  CLEAR
======================================================================"""
