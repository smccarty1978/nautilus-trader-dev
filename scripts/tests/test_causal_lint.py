"""Behavioral tests for scripts/causal_lint.py.

Each positive case is drawn from a defect class that a paid LLM audit pass
actually found in this repository. If a rule stops firing, these fail.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "causal_lint", REPO_ROOT / "scripts" / "causal_lint.py"
)
causal_lint = importlib.util.module_from_spec(_spec)
sys.modules["causal_lint"] = causal_lint
_spec.loader.exec_module(causal_lint)


def scan_src(tmp_path: Path, src: str):
    f = tmp_path / "mod.py"
    f.write_text(src, encoding="utf-8")
    return causal_lint.scan_file(f)


def rule_ids(findings):
    return {f.rule_id for f in findings}


# --------------------------------------------------------------------------
# Positive cases -- these MUST be caught
# --------------------------------------------------------------------------

@pytest.mark.parametrize("src,expected", [
    # H4 -- the single most repeated finding in repo history
    ("exit_pnl = (sl_px - entry_px) * direction * MULT", "H4"),
    ("pnl = (stop_px - entry_px) * d", "H4"),
    # H1 -- stop detection on close
    ("if close <= stop_px:\n    pass", "H1"),
    # A1/F1 -- session gate reading the bar's OPEN time (real defect)
    ("in_rth = is_rth(bar.ts_event)", "A1/F1"),
    # A1-naming -- bare identifier named ts_event in session code (hazard only)
    ("minute_of_day = to_minute(ts_event)", "A1-naming"),
    # A5/G3 -- resample boundary look-ahead
    ("df.resample('1min', label='right', closed='right').last()", "A5/G3"),
    # B1 -- centered rolling
    ("df['ma'] = df.c.rolling(20, center=True).mean()", "B1"),
    # B4 -- negative shift
    ("df['y'] = df.close.shift(-5)", "B4"),
    # B5 -- backfill
    ("df['atr'] = df.atr.bfill()", "B5"),
    ("df = df.fillna(method='bfill')", "B5"),
    # B6 -- merge_asof without direction
    ("out = pd.merge_asof(a, b, on='ts')", "B6"),
    ("out = pd.merge_asof(a, b, on='ts', direction='forward')", "B6"),
    # C3 -- random split on time series
    ("X_tr, X_te = train_test_split(X, test_size=0.2)", "C3"),
    ("scores = cross_val_score(m, X, y, cv=5)", "C3"),
    # G1 -- non volume-continuous contract
    ("SYMBOL = 'NQ.c.0'", "G1"),
])
def test_rule_fires(tmp_path, src, expected):
    assert expected in rule_ids(scan_src(tmp_path, src)), (
        f"rule {expected} failed to fire on: {src!r}"
    )


# --------------------------------------------------------------------------
# Negative cases -- these must NOT be reported
# --------------------------------------------------------------------------

@pytest.mark.parametrize("src", [
    # correct close-time session gate
    "in_rth = is_rth(bar.ts_init)",
    # correct resample boundary
    "df.resample('1min', label='right', closed='left').last()",
    # explicit backward merge
    "out = pd.merge_asof(a, b, on='ts', direction='backward')",
    # temporal CV
    "cv = TimeSeriesSplit(n_splits=5)\nscores = cross_val_score(m, X, y, cv=cv)",
    # volume-continuous symbol is the mandated one
    "SYMBOL = 'NQ.v.0'",
    # plain causal rolling
    "df['ma'] = df.c.rolling(20).mean()",
])
def test_no_false_positive(tmp_path, src):
    assert scan_src(tmp_path, src) == [], f"false positive on: {src!r}"


def test_comments_do_not_trigger(tmp_path):
    src = "# we must never use center=True here\nx = 1\n"
    assert scan_src(tmp_path, src) == []


def test_ts_event_outside_session_context_is_clean(tmp_path):
    # ts_event is legitimate when not classifying a session
    assert scan_src(tmp_path, "raw_open_ns = bar.ts_event") == []


def test_attribute_access_is_critical_but_bare_name_is_only_a_warning(tmp_path):
    """The two tiers must not collapse into each other.

    Reading `bar.ts_event` in a session gate is a live defect. A parameter
    merely *named* ts_event that receives ts_init is a naming hazard -- it
    should be visible without blocking the gate.
    """
    crit = scan_src(tmp_path, "in_rth = classify_session(bar.ts_event)")
    assert [f.severity for f in crit] == ["CRITICAL"]

    warn = scan_src(tmp_path, "def reset_rth(self, ts_event: int) -> None:")
    assert [f.severity for f in warn] == ["WARNING"]


# --------------------------------------------------------------------------
# Suppression protocol
# --------------------------------------------------------------------------

def test_pragma_with_reason_suppresses(tmp_path):
    src = "df['y'] = df.close.shift(-5)  # causal-lint: ignore[B4] label column"
    assert rule_ids(scan_src(tmp_path, src)) == set()


def test_bare_pragma_is_itself_reported(tmp_path):
    src = "df['y'] = df.close.shift(-5)  # causal-lint: ignore[B4]"
    findings = scan_src(tmp_path, src)
    assert any(f.rule_id == "LINT" for f in findings), (
        "a suppression with no stated reason must be reported"
    )


def test_pragma_does_not_suppress_other_rules(tmp_path):
    src = "df['y'] = df.c.rolling(3, center=True).mean()  # causal-lint: ignore[B4] unrelated"
    assert "B1" in rule_ids(scan_src(tmp_path, src))
