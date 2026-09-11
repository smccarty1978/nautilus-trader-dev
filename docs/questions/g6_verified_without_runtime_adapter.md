# G6 — `verified` in the feature registry does not mean anything can produce the feature

    status:   RECORDED, NOT FIXED
    found by: nq_mtf_regime_atlas_pilot2023 (phase B, 2026-09-11), recorded from the
              G7 chore session 2026-09-11. Its own packet; not fixed here.
    surface:  research_workflow/capabilities/registry.json (kinds.features),
              research_workflow/provider_host.py, features/definitions/, WORKFLOW.md §E

## The claim the registry makes

`research cap describe feature.session_membership` returns

    "status": "verified", "implementation": "features.trackers.generic_context.GenericContextProvider",
    "implementation_exists": true

A reader takes that as "this feature is available". It is not what the field means. `verified`
is evidence that **the definition computes what it claims** (golden values, determinism, causal
availability — the `research feature verify|promote` path). It says nothing about whether any
**runtime adapter** in `research_workflow/provider_host.py` will emit the column during a replay.

## What was measured (this session, on `main` at 451836f8)

145 features are registered. Every one of them has `status: verified`.

**50 of the 145 name a canonical provider that is not in `provider_host.py`'s adapter registry
at all** — the seven `canonical_provider` keys at `provider_host.py:852-858`. Nothing can
instantiate them. The providers with no adapter:

    GenericMedianCenterCompatibilityProvider   (19 features)
    GenericPullbackProvider                    (11)
    GenericArrivalVolumeProvider                (7, incl. relative_volume)
    GenericPriceLevelProvider                   (5)
    GenericRangeATRProvider / GenericRangePositionProvider / GenericWickImbalanceProvider (1 each)

Separately, a provider that **does** have an adapter may still not render a given feature:
`ContextAdapter` (`provider_host.py:219`) owns `GenericContextProvider` but renders only
`ema_slope`, so `session_membership`, `session_elapsed` and `regime_age` bind to an adapter that
will not emit them.

Both cases are caught at compile, with two different messages:

    feature: relative_volume      -> MISSING_CAPABILITY features.instances
                                     "RUNTIME_PROVIDER_BINDING_MISSING: canonical provider ..."
    feature: session_membership   -> MISSING_CAPABILITY features.instances
                                     "no runtime adapter renders 'session_membership'"
    feature: regime_efficiency    -> compiles and binds (control)

## Why it matters, framed exactly

The compiler is not the problem — it refuses correctly, and early. The problem is the
**promotion path and the registry it writes**. `verified` is the field a researcher reads when
deciding what a study can declare, and it currently over-promises for a third of the catalogue.
The pilot lost a session to it twice: the ETH/RTH flag (`feature.session_membership`) and the
VOLUME block (`feature.relative_volume`) were both chosen off the registry, and both had to be
re-derived from other columns after the compile refused them
(`studies/nq_mtf_regime_atlas_pilot2023/CAPABILITY_GAP_HANDOFF.md`, `eth_rth_flag` and
`volume_block`).

It will mislead the next reader the same way.

## What a fix would have to decide (not decided here)

- whether `verified` splits into two fields (definition-verified vs. runtime-producible), or
  whether promotion simply refuses to mark a definition `verified` until an adapter renders it;
- whether `research cap search` / `describe` surfaces producibility in its card;
- whether the 50 unadapted definitions get adapters, get demoted, or get a third status.

Feature promotion by golden evidence is `chore/feature_promotion` (`fa9d7197`, not merged as of
2026-09-11); that branch is where the answer belongs.
