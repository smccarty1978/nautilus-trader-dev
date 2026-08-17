# Feature Registry Contract

This is the authoritative contract governing the feature engineering system in this repository.

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
3. An entry in `features/feature_lifecycle_promotions.json` naming the `causal_audit_artifact` that cleared
   it, the `audited_execution_composite_sha256` reviewed, and `promoted_by`. Auditor
   clearance cannot be inferred from the tree, so it is required explicitly rather than
   assumed from silence.

`features/feature_lifecycle_baseline.json` grandfathers the 502 features that already carried
`verified` when this check was introduced. That list may **shrink** as evidence is added;
adding a name to it is refused, so it cannot be used to launder a new feature.

The gate runs in `scripts/research_preflight.py` and again in
`scripts/build_phase0_manifest.py`, which is where `verified` becomes an eligible
candidate universe. Regression coverage: `scripts/tests/test_feature_promotion.py`.

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

Every registered feature must be defined in [features/registry.py](file:///c:/Users/Scott%20McCarty/Projects/Nautilus%20Trader/features/registry.py) using the `FeatureDefinition` data class:

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

* Registry-level aliases are supported solely for backwards-compatibility migrations.
* Emitting deprecated aliases in new study datasets is strictly prohibited.
* Querying a deprecated alias maps the key to the canonical feature internally, but issues a runtime `DeprecationWarning` to alert developers to update the study.

---

## 8. Migration and Requests

1. **How to Request a Feature:** Developers must create a provisional ticket in `FEATURE_REGISTRY_CONTRACT.md` before coding.
2. **Migration Paths:** All new worktree strategy versions must consume features via the `FeatureEngine` composition pattern.
