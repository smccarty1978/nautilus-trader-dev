# Feature Registry Contract

This is the authoritative contract governing the feature engineering system in this repository.

> **Read §0 first.** Feature System V2 is active and the runtime is canonical-only.
> Sections 2–8 below predate the V2 migration: their *principles* still hold, but where a
> section names a physical feature (`arrival_vel_5s`, `pullback_depth_atr`) or a
> timeframe-specific update method, read it as describing an **instance**, not an identity.
> `docs/RESEARCH_WORKFLOW.md` §2 is the current description.

---

## 0. Canonical identity (Feature System V2)

A **canonical feature definition** names exactly five things:

- the **formula**
- the **provider** (the implementation that computes it)
- its **causal semantics** — what input it may see, and when
- its **reset semantics**
- its **null semantics**

Everything else is a **parameter of a `FeatureInstance`**, never a separate feature:

```
timeframe   window   lookback   period   context   bar_state   update_every
source_timeframe   reference_timeframe   input_timeframe   ema_role
```

> **"1m EMA" is NOT a separately named feature.** Timeframe belongs in the parameters.

```yaml
# study.yaml — CORRECT
features:
  source: canonical_verified_definition_universe
  instances:
    - feature: regime_efficiency
      parameters: {timeframe: 5m, context: prior, bar_state: completed}
    - feature: rolling_giveback_atr
      parameters: {window: 300s, update_every: 1s}
```

`prior_5m_regime_efficiency` and `rolling_300s_giveback_atr` are **output column aliases**,
generated deterministically by `generate_physical_alias()`. Verification status lives on the
canonical definition, never on the alias.

### Three temporal semantics that must stay distinct

| Meaning | Parameters |
|---|---|
| Completed calendar bar | `timeframe: 1m, bar_state: completed` |
| Forming calendar bar | `timeframe: 1m, bar_state: forming, update_every: 5s` |
| True rolling window | `window: 300s, update_every: 1s` |

`validate_feature_instance()` fails closed rather than guessing —
`AMBIGUOUS_TEMPORAL_SEMANTICS`, `FORMING_BAR_UPDATE_REQUIRED`,
`COMPLETED_BAR_UPDATE_FREQUENCY_INVALID`, `ROLLING_WINDOW_UPDATE_REQUIRED`,
`FORMING_BAR_UNSUPPORTED`, and the rest are listed in `docs/RESEARCH_WORKFLOW.md` §2.
**Never resolve one of these by adding a default.**

### Authority

The active canonical bundle is selected by an atomic pointer, `features/authority/active.json`
(currently `activation_kind: feature_pipeline_v2` — 129 canonical definitions, 693 legacy
aliases with deterministic parity evidence). `features/candidate_authority.load_authority()` is
the only loader; a candidate is never selected by environment variable, ambient state, or
fallback.

`features/CANONICAL_FEATURE_REFERENCE.yaml` is the generated, shareable vocabulary. Check it
before proposing a new feature.

### Legacy / alias policy

| | |
|---|---|
| Active runtime | canonical only |
| `source: canonical_verified_definition_universe` | the active path |
| `source: verified_registry_numeric_universe` | raises `LEGACY_FEATURE_ALIAS_NOT_ALLOWED` unless `legacy_mode=True` |
| Active fallback to legacy aliases | **prohibited** — there is none, and none may be added |
| New studies using physical alias names | **prohibited** |
| Historical replay | explicit, isolated `legacy_mode=True` only |
| `features/archive/legacy_registry_2026_08_22/` | V1 rollback archive, non-runtime |

### Adding a provider

Do **not** add a provider to support another timeframe, window, or period — that is a
parameter. Extend or add a parameterized provider under `features/trackers/generic_*.py`
only when the formula or the state-transition semantics genuinely differ. Document and test
that difference before implementing it.

---

## Two-Layer Architecture

To maintain performance, reproducibility, and prevent look-ahead bias:
1. **Centralized Reusable Calculations (The Library):** Defines *how* features are calculated. Managed by `features/library.py`, `features/registry.py`, and `features/engine.py`.
2. **Study-Specific Feature Contract (The Study SPEC):** Defines *when* features are updated and snapped. Each collector/strategy must define its own anchors, normalizations, and default values.

```
+---------------------------------------+
|          Centralized Library          |
|    - How features are calculated      |
|    - State trackers & indicators      |
+---------------------------------------+
                    |
                    v
+---------------------------------------+
|         Study-Specific SPEC           |
|    - When to update & snap features   |
|    - Normalization ATR references     |
+---------------------------------------+
```

---

## 1. Feature Lifecycle & Canonicalization

A feature must move through four explicit statuses:
* **`archived`:** Legacy calculations preserved in `archive/` or inactive.
* **`provisional`:** New calculations implemented but not fully verified against historical baselines or look-ahead audits. **Every new feature starts here.**
* **`verified`:** Validated via:
  - Formula review.
  - Warmup review.
  - Prefix-invariance testing.
  - Parity comparison with historical implementations.
  - Look-ahead auditor clearance.
* **`deprecated`:** Older names or calculations that have been succeeded by a canonical feature. Trigger a runtime `DeprecationWarning` upon query and should be completely avoided in new studies.

### Promotion is enforced, not advisory

This list was prose only until `latest_1m_wick_imbalance` was registered as `verified` in
the same change that implemented it — the registry entry asserted the outcome of reviews
that had not run. `scripts/check_feature_promotion.py` now enforces the lifecycle:

```
NEW FEATURE -> provisional -> deterministic evidence -> explicit promotion -> verified
```

A feature reaching `verified` must satisfy all three, and the check fails closed:

1. `implementation` resolves to a module that exists on disk.
2. At least one declared test file exists **and names the feature**. A test that never
   mentions the feature is not evidence about that feature.
3. An explicit promotion record naming the `causal_audit_artifact` that cleared it, the
   `audited_execution_composite_sha256` reviewed, and `promoted_by`. Auditor clearance cannot
   be inferred from the tree, so it is required explicitly rather than assumed from silence.

   Two promotion files, one per generation:

   | File | Governs |
   |---|---|
   | `features/feature_definition_promotions.json` | **canonical V2 definitions** — read by `canonical_definition_status()` and `check_canonical_feature_promotions()` |
   | `features/feature_lifecycle_promotions.json` | V1 physical features. Absent since the V1 archive, which is a legitimate deny-state: a missing promotions file grants nothing (unlike a missing baseline) |

`features/feature_lifecycle_baseline.json` grandfathers the 502 features that already carried
`verified` when this check was introduced. That list may **shrink** as evidence is added;
adding a name to it is refused, so it cannot be used to launder a new feature.

The gate runs in `research_workflow/preflight.py` (as the `FEATURE_PROMOTION` required check)
and again in `research_workflow/phase0.py`, which is where `verified` becomes an eligible
candidate universe. `scripts/research_preflight.py` and `scripts/build_phase0_manifest.py`
are compatibility shims for those modules. Regression coverage:
`scripts/tests/test_feature_promotion.py`. Governance CLI: `python scripts/feature_ctl.py`.

---

## 2. No Implicit or Undocumented Timeframe Assumptions

A tracker must not contain undocumented or implicit timeframe assumptions. Its window unit, update cadence, reset policy, warmup, and normalization must be explicit.

### Tracker Parameterization
Trackers should be parameterized explicitly in configuration or constructor signature:
* **`window`:** Lookback/window value (e.g. 30).
* **`window_unit`:** The unit of the lookback value. Allowed units:
  - `bars`
  - `seconds`
  - `minutes`
  - `events`
  - `session`
  - `since_signal`
  - `since_regime_flip`
* **`warmup`:** Warmup requirement in units.
* **`reset_policy`:** The policy for clearing state (e.g. `event_start`, `session_boundary`, `none`).
* **`normalization`:** Normalization reference (e.g. `study_contract`, `atr`).

### Stream Routing Boundary
The `FeatureEngine` controls routing. The tracker must not check the bar type internally (e.g., `if bar.bar_type == "1-SECOND"`), unless different bar types require different calculations.

```python
# The engine routes observations explicitly
def update_1s(self, bar):
    self.velocity_1s.update(bar.close)

def update_1m(self, bar):
    self.velocity_1m.update(bar.close)
```

---

## 3. Required Registry Metadata

> A **canonical V2 definition** additionally declares `parameter_schema`,
> `supported_bar_states`, `supported_timeframes`, `supported_update_every`,
> `required_parameters`, `supported_parameter_values` and `supported_parameter_combinations`.
> Those fields are what make `validate_feature_instance()` able to fail closed, and they are
> what a study's `FeatureInstance` is validated against. The example below is the base
> record; it is not sufficient on its own for a canonical definition.

Every registered feature is defined in `features/registry.py` using the `FeatureDefinition`
data class:

```python
FeatureDefinition(
    name="pullback_depth_atr",
    aliases=("pb_depth_atr",),
    version="1.0",
    status="verified",
    family="pullback",
    stateful=True,
    source_timeframe="1s",
    update_anchor="after_1s_close",
    snapshot_anchor="caller_defined",
    warmup=None,
    normalizer="study_contract",
    direction_normalized=True,
    dtype="float64",
    null_policy="disallow",
    implementation="features.trackers.pullback.PullbackTracker",
    tests=("tests/test_feature_library.py",),
    parity_tolerance="tight",
    window=None,
    window_unit=None,  # bars|seconds|minutes|events|session|since_signal|since_regime_flip
    reset_policy="none",  # e.g. event_start, session_boundary, none
)
```

---

## 4. Stateful vs. Stateless Features

* **Stateless Features:** Calculated on-demand from the current bar values (e.g. `is_rth`, `minutes_since_rth_open`).
* **Stateful Features:** Depend on historical sequences or rolling buffers (e.g. `arrival_vel_5s`, `pullback_depth_atr`). They must update on specific bar closures (e.g., `1s` close, `1m` close) and maintain their internal states within the `FeatureEngine`.

---

## 5. Timeframe Update Ownership

State updates must be driven by explicit callbacks matching the source timeframe:
* **`1s` updates:** Feed into `update_1s()`.
* **`30s` updates:** Feed into `update_30s()`.
* **`1m` updates:** Feed into `update_1m()`.
* **`5m` updates:** Feed into `update_5m()`.

---

## 6. Snapshot Semantics

Exact snapshot timings must remain part of the study-specific contract. The study-specific strategy queries a snapshot of canonical features at a specific decision timestamp (e.g. at touch time) and normalizes values using the event-specific ATR denominator (`atr_at_signal`). Previously returned snapshots must remain immutable.

---

## 7. Alias and Deprecation Policy

Under V2 there are two distinct things called "alias". Do not conflate them.

**Physical alias (output column name).** Generated deterministically from a `FeatureInstance`
by `generate_physical_alias()`. Legitimate, and how collector output stays readable. It is an
*output*, never a study input: a study contract declares `feature` + `parameters`.

**Legacy alias (V1 compatibility mapping).** The 693 entries in
`features/authority/candidate/legacy_alias_mapping.json`. Resolution requires an explicit
`legacy_mode=True` historical replay and otherwise raises `LEGACY_FEATURE_ALIAS_NOT_ALLOWED`.

* There is **no active fallback** to legacy aliases, and none may be added.
* Declaring a legacy alias in a new study is prohibited.
* Registry-level `aliases=(...)` on a `FeatureDefinition` remains a backwards-compatibility
  migration device only; querying one issues a runtime `DeprecationWarning`.

---

## 8. Migration and Requests

1. **How to request a feature:** resolve the request first —
   `python scripts/feature_ctl.py`. If it resolves, declare a `FeatureInstance`; you are done.
   If it is a genuine miss, `feature_ctl` emits a copy/paste canonical-definition draft
   (`canonical_name`, `family`, `provider`, `parameters`, `temporal_semantics`,
   `null_policy`, `reset_policy`, `tests`, `causal_requirements`). Fill it in, add tests that
   name the feature, and promote it through §1.
2. **Do not add a provider for another timeframe, window, or period.** That is a parameter.
3. **Migration path:** studies consume features by declaring canonical `FeatureInstance`s in
   `study.yaml`. The compiler derives the provider dependency closure; the generic collector
   executes it. Never import, wrap, or subclass a historical study collector.
