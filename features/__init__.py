"""Feature Library Package.

Deliberately empty: importing ``features`` (or any ``features.*`` submodule) must not import the
feature registry, the engine or any tracker. Import what you use from its module
(``features.registry``, ``features.engine``, ``features.trackers.<name>``). The re-exports that used
to live here made every module under ``features`` pull ``features/registry.py`` into its import
closure, so a one-line feature definition reached 139 of 178 test files (chore/tiered_gates, 2026-09-08).
"""
