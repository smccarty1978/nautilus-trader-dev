"""Provider identities shared by more than one definition catalogue.

Two providers serve both a physical output-alias family and a canonical V2 definition family
(structural regime geometry, rolling productivity).  Their dotted implementation path and the
tests that vouch for them are one fact, declared once here rather than repeated per catalogue.

Part of the definitions package: imported by definition modules, never by the resolver or by a
consumer.
"""

STRUCTURAL_IMPL = 'features.trackers.generic_structural_geometry.GenericStructuralGeometryProvider'
STRUCTURAL_TESTS = ('studies/Codex_structural_regime_geometry_maturity/tests/test_geometry_tracker.py',)

ROLLING_PRODUCTIVITY_IMPL = 'features.trackers.rolling_5m_productivity.Rolling5mProductivityTracker'
ROLLING_PRODUCTIVITY_TESTS = ('studies/Codex_clean_maturity_flip_rolling_5m_productivity/tests/test_rolling_5m_productivity.py',)
