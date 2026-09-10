"""Canonical feature definition record: ``structural_max_expansion_checkpoint_atr``.

One definition per module (data only); discovered by ``features.definitions.canonical``
in filename order and merged by ``features.registry``.  Nothing imports this module by name.

Maximum structural expansion of the current 1m regime (favourable extreme minus the structural
origin, i.e. the prior regime's opposite extreme) normalised by the CHECKPOINT-EPOCH ATR
(``checkpoint_atr`` handed to the structural geometry snapshot -- the study's ``family_a_atr``
binding) instead of the regime-start frozen ATR used by ``structural_max_expansion_atr``.
Semantics, availability, warmup, reset and null policy are otherwise identical to that sibling;
only the normaliser differs.  Emitted by the same provider snapshot; verified by its own golden
evidence (``features/definitions/golden/structural_max_expansion_checkpoint_atr.json``).
"""
from features.feature_types import FeatureDefinition
from features.definitions.providers import STRUCTURAL_IMPL, STRUCTURAL_TESTS

DEFINITION = FeatureDefinition(
    name='structural_max_expansion_checkpoint_atr',
    status='provisional',
    family='structural_regime_geometry',
    source_timeframe='1s+1m+5m',
    update_anchor='completed_1s_completed_5m_then_1m_flip',
    normalizer='checkpoint_atr',
    null_policy='allow',
    implementation=STRUCTURAL_IMPL,
    tests=STRUCTURAL_TESTS,
    window_unit='since_regime_flip',
    reset_policy='event_start',
    parameter_schema=('context',),
    supported_timeframes=('1m', '5m', '5s'),
    supported_parameter_values={
        'context': ('current',),
    },
    required_parameters=('context',),
    supported_parameter_combinations=(
        {
            'context': 'current',
        },
    ),
    coverage_family='structural_regime_geometry',
)
