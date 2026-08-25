"""The fused ring-buffer path is selected by capability, not by feature count.

`research_workflow/generic_collector.py` used to gate its ring-buffer snapshot path on
`len(config.feature_list) == 60`. 60 is the cardinality of the surface that path can
produce (25 inline OHLCV/delta/price-level/RTH keys + 27 structural + 8 rolling), so the
check accepted *any* unrelated 60-name surface and rejected *every* valid subset of the
real one.

The capability it was really reaching for is: the declared surface is servable by that
path AND actually spans the provider block, because a base-block-only surface has always
been served by the per-tracker path and computes the same column names differently.

These tests pin both halves: the constant does not drift from the code that produces it,
and the selection is driven by what a study declares rather than how many things it declares.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_workflow.generic_collector import (  # noqa: E402
    _FUSED_BASE_BLOCK, _FUSED_PROVIDER_BLOCK, _FUSED_RING_SURFACE,
)

COLLECTOR = REPO_ROOT / "research_workflow" / "generic_collector.py"

# The historical study that declares the full fused surface. It is the authority for what
# that surface *is*; the collector must not name it, but a test may.
HISTORICAL_60 = REPO_ROOT / "studies" / "Gemini_clean_maturity_flip_rolling_5m_productivity"


def _declared_surface(study: Path) -> list[str]:
    compiled = json.loads((study / "compiled_study.json").read_text(encoding="utf-8"))
    return compiled["spec"]["features"]["feature_list"]


def _selects_fused_path(feature_list) -> bool:
    """The exact predicate the collector applies, evaluated without building an engine."""
    declared = set(feature_list or ())
    return (bool(declared) and declared.issubset(_FUSED_RING_SURFACE)
            and bool(declared & _FUSED_PROVIDER_BLOCK))


# --- the constant must not drift from the code that produces the surface ----------

def _inline_keys_of_all_computed_60() -> list[str]:
    tree = ast.parse(COLLECTOR.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "all_computed_60" for t in node.targets
        ):
            return [k.value for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
    pytest.fail("all_computed_60 literal not found; the fused snapshot path moved")


def test_inline_snapshot_keys_are_exactly_the_base_block():
    """The declared base block must equal the keys the fused dict builds inline."""
    inline = set(_inline_keys_of_all_computed_60())
    assert inline, "no inline keys parsed"
    assert inline == _FUSED_BASE_BLOCK, (
        f"base block drifted; only-in-code={sorted(inline - _FUSED_BASE_BLOCK)} "
        f"only-in-constant={sorted(_FUSED_BASE_BLOCK - inline)}"
    )


def test_fused_surface_matches_the_historical_full_surface():
    """The constant is the historical 60-name surface, exactly."""
    declared = _declared_surface(HISTORICAL_60)
    assert set(declared) == _FUSED_RING_SURFACE
    assert len(_FUSED_RING_SURFACE) == len(declared) == 60


def test_fused_dict_still_spreads_structural_and_rolling():
    """The other 35 names arrive via two ** spreads; if those go, the constant is wrong."""
    tree = ast.parse(COLLECTOR.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "all_computed_60" for t in node.targets
        ):
            assert sum(1 for k in node.value.keys if k is None) == 2
            return
    pytest.fail("all_computed_60 literal not found")


# --- A. the historical 60-feature study still takes the fused path ----------------

def test_historical_sixty_feature_study_still_selects_fused_path():
    assert _selects_fused_path(_declared_surface(HISTORICAL_60)) is True


# --- B. same capability, different count -> same path -----------------------------

@pytest.mark.parametrize("n_base,n_provider", [(0, 1), (1, 1), (10, 5), (25, 34)])
def test_subset_spanning_the_provider_block_selects_fused_path(n_base, n_provider):
    """Same capability, different count: any surface spanning the provider block."""
    subset = sorted(_FUSED_BASE_BLOCK)[:n_base] + sorted(_FUSED_PROVIDER_BLOCK)[:n_provider]
    assert len(subset) == n_base + n_provider != 60
    assert _selects_fused_path(subset) is True, f"{len(subset)}-feature subset was rejected"


def test_base_block_only_surface_keeps_the_per_tracker_path():
    """The base block alone has always been served by the trackers. Do not switch it.

    `bespoke_population_parity_smoke` and `reconstructed_long_rth_strict_retrain` both
    declare exactly these 25 names. Routing them through the fused snapshot would be a
    different computation of the same columns -- a silent value change.
    """
    assert _selects_fused_path(sorted(_FUSED_BASE_BLOCK)) is False


# --- C. same count (60), different capability -> NOT the fused path ---------------

def test_sixty_unrelated_features_do_not_select_fused_path():
    """The old check accepted this purely because it counted 60."""
    unrelated = [f"unrelated_feature_{i}" for i in range(60)]
    assert len(unrelated) == 60
    assert _selects_fused_path(unrelated) is False


def test_one_foreign_feature_disqualifies_the_fused_path():
    """59 servable + 1 unservable must not take a path that cannot produce it."""
    mixed = sorted(_FUSED_RING_SURFACE)[:59] + ["latest_1m_wick_imbalance"]
    assert len(mixed) == 60
    assert _selects_fused_path(mixed) is False


def test_blocks_partition_the_surface_exactly():
    assert _FUSED_BASE_BLOCK | _FUSED_PROVIDER_BLOCK == _FUSED_RING_SURFACE
    assert not (_FUSED_BASE_BLOCK & _FUSED_PROVIDER_BLOCK)
    assert len(_FUSED_BASE_BLOCK) == 25 and len(_FUSED_PROVIDER_BLOCK) == 35


def test_no_existing_study_changes_collector_path():
    """Exact-behaviour proof against every compiled study in the repo."""
    changed = []
    for cs in sorted((REPO_ROOT / "studies").glob("*/compiled_study.json")):
        try:
            fl = (json.loads(cs.read_text(encoding="utf-8")).get("spec", {})
                  .get("features", {}) or {}).get("feature_list")
        except Exception:
            continue
        old = bool(fl and len(fl) == 60)          # the removed gate
        if old != _selects_fused_path(fl):
            changed.append(cs.parent.name)
    assert not changed, f"collector path changed for existing studies: {changed}"


# --- D. ordinary small studies are unaffected -------------------------------------

def test_empty_feature_list_does_not_select_fused_path():
    """V2 studies declare `instances` and leave feature_list None -- the compact path."""
    assert _selects_fused_path(None) is False
    assert _selects_fused_path([]) is False


@pytest.mark.parametrize("study_name,expected", [
    # Declares instances only; feature_list is None -> compact path, never fused.
    ("clean_maturity_flip_model_rolling_productivity", False),
    ("test_minimal_checkpoint_collector", False),
    ("test_level_break_collector", False),
    ("ym_prev5_range_position", False),
])
def test_real_small_studies_are_unaffected(study_name, expected):
    study = REPO_ROOT / "studies" / study_name
    if not (study / "compiled_study.json").is_file():
        pytest.skip(f"{study_name} not compiled in this checkout")
    compiled = json.loads((study / "compiled_study.json").read_text(encoding="utf-8"))
    assert _selects_fused_path(compiled["spec"]["features"].get("feature_list")) is expected


# --- the old behaviour must not be reachable again --------------------------------

def test_no_feature_count_gate_remains_in_the_collector():
    src = COLLECTOR.read_text(encoding="utf-8")
    assert "_is_targeted_60" not in src
    tree = ast.parse(src)
    offenders = [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Call) and isinstance(node.left.func, ast.Name)
        and node.left.func.id == "len"
        and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
        and any(isinstance(c, ast.Constant) and isinstance(c.value, int) and c.value > 1
                for c in node.comparators)
    ]
    assert not offenders, f"a length-vs-constant gate returned at lines {offenders}"
