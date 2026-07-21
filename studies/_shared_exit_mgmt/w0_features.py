"""W0 feature family: local progress/giveback only.

Population-agnostic: pure column-selection + split-labeling logic
operating on any atlas produced by build_atlas.py. No population-
specific assumptions.

IMPORTANT: W0_FEATURES excludes every forward-looking column
(remaining_*, eventual_*, terminal_weakness_label) -- those are
labels/diagnostics only, never inputs, per CLAUDE.md's ML label rule
and studies/_shared_exit_mgmt/build_atlas.py's module docstring.
"""
from __future__ import annotations
import pandas as pd

W0_FEATURES = [
    "current_pnl_atr_from_entry",
    "mfe_atr_from_entry",
    "mae_atr_from_entry",
    "giveback_atr_from_entry",
    "distance_from_mfe_atr",
    "age_seconds",
]

TARGET_COL = "is_terminal_weakness"

SPLIT_BOUNDARIES = {
    "train": (pd.Timestamp("2021-01-01", tz="UTC"),
                 pd.Timestamp("2025-01-01", tz="UTC")),
    "validation": (pd.Timestamp("2025-01-01", tz="UTC"),
                      pd.Timestamp("2025-03-01", tz="UTC")),
    "dev_test": (pd.Timestamp("2025-03-01", tz="UTC"),
                    pd.Timestamp("2026-01-01", tz="UTC")),
    "reserved_eval": (pd.Timestamp("2026-01-01", tz="UTC"),
                          pd.Timestamp("2026-05-01", tz="UTC")),
}


def add_target(atlas: pd.DataFrame) -> pd.DataFrame:
    atlas = atlas.copy()
    atlas[TARGET_COL] = (
        atlas["terminal_weakness_label"] == "TERMINAL_WEAKNESS")
    return atlas


def add_split_label(atlas: pd.DataFrame) -> pd.DataFrame:
    """Chronological split by entry_ts (trade-level) -- every checkpoint
    of a given trade falls in exactly one split, never straddling a
    boundary."""
    atlas = atlas.copy()
    entry_dt = pd.to_datetime(atlas["entry_ts"], unit="ns", utc=True)
    split = pd.Series("unassigned", index=atlas.index, dtype="object")
    for name, (start, end) in SPLIT_BOUNDARIES.items():
        mask = (entry_dt >= start) & (entry_dt < end)
        split[mask] = name
    atlas["split"] = split.astype("category")
    return atlas
