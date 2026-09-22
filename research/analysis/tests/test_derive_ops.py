"""``analysis.derive.columns`` -- through the registered op (``research.analysis.ops.run_op``)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from research.analysis.expressions import ExpressionError, canonical, expand_columns, parse, static_check
from research.analysis.ops import AnalysisOpError, known_ops, run_op

NS = 1_000_000_000


def derive(frame, columns, **kw):
    return run_op("analysis.derive.columns", frame, params={"columns": columns, **kw})


@pytest.fixture()
def atlas_like():
    """Four trades shaped like the atlas frame: one long above a level, one short above it, one
    with a zero HTF ATR, one with a null entry (unavailable)."""
    return pd.DataFrame({
        "dir_1m": [1, -1, 1, 1],
        "dir_5m": [1, 1, -1, 1],
        "executable_entry_price": [15_010.0, 15_010.0, 15_000.0, np.nan],
        "start_price_5m": [15_000.0, 15_000.0, 15_020.0, 15_000.0],
        "highest_high_5m": [15_030.0, 15_030.0, 15_040.0, 15_030.0],
        "lowest_low_5m": [14_990.0, 14_990.0, 14_990.0, 14_990.0],
        "frozen_atr_5m": [20.0, 20.0, 0.0, 20.0],
        "atr_entry_1m": [5.0, 5.0, 4.0, 5.0],
        "executable_entry_ts": pd.array([100 * NS, 100 * NS, 100 * NS, None], dtype="Int64"),
        "terminal_flip_ts": pd.array([400 * NS, 150 * NS, None, 400 * NS], dtype="Int64"),
        "fp_fav_1p00_disposition": ["POSITIVE", "POSITIVE", "POSITIVE", None],
        "fp_fav_1p00_resolution_seconds": [120.0, 50.0, 30.0, np.nan],
        "fp_adv_0p50_resolution_seconds": [200.0, 50.0, np.nan, 10.0],
        "checkpoint_index": [0, 0, 0, 15],
    })


def test_registered():
    assert "analysis.derive.columns" in known_ops()


def test_arithmetic_column_scalar_and_column_column():
    f = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [10.0, 20.0, 30.0]})
    out = derive(f, [{"name": "s", "expr": "a + b"}, {"name": "d", "expr": "b - a"}, {"name": "m", "expr": "a * 2.5"},
                     {"name": "p", "expr": "a + 1"}, {"name": "q", "expr": "b / a"}, {"name": "n", "expr": "-a"}])["frame"]
    assert out["s"].tolist() == [11.0, 22.0, 33.0]
    assert out["d"].tolist() == [9.0, 18.0, 27.0]
    assert out["m"].tolist() == [2.5, 5.0, 7.5]
    assert out["p"].tolist() == [2.0, 3.0, 4.0]
    assert out["q"].tolist() == [10.0, 10.0, 10.0]
    assert out["n"].tolist() == [-1.0, -2.0, -3.0]


def test_precedence_and_parentheses():
    f = pd.DataFrame({"a": [2.0]})
    out = derive(f, [{"name": "x", "expr": "1 + a * 3"}, {"name": "y", "expr": "(1 + a) * 3"}, {"name": "z", "expr": "- a * -2"}])["frame"]
    assert (out["x"][0], out["y"][0], out["z"][0]) == (7.0, 9.0, 4.0)


def test_signed_direction_normalized_distance_htf_and_1m_atr(atlas_like):
    cols = [{"name": "sd_cur_start_5m_{X}", "expr": "dir_1m * (executable_entry_price - start_price_5m) / {den}",
             "each": {"X": ["A"], "den": ["frozen_atr_5m"]}},
            {"name": "sd_cur_start_5m_B", "expr": "dir_1m * (executable_entry_price - start_price_5m) / atr_entry_1m"},
            {"name": "ad_cur_start_5m_A", "expr": "abs(executable_entry_price - start_price_5m) / frozen_atr_5m"},
            {"name": "ad_cur_start_5m_B", "expr": "abs(executable_entry_price - start_price_5m) / atr_entry_1m"}]
    out = derive(atlas_like, cols)["frame"]
    # long 10 pts above the start: favourable side, +0.5 HTF-ATR, +2.0 trade-ATR
    assert out["sd_cur_start_5m_A"][0] == 0.5 and out["sd_cur_start_5m_B"][0] == 2.0
    # a SHORT 10 pts above the level is on the UNFAVOURABLE side -> negative; absolute unchanged
    assert out["sd_cur_start_5m_A"][1] == -0.5 and out["ad_cur_start_5m_A"][1] == 0.5
    # zero HTF ATR -> A is NULL (no_atr), B still defined
    assert math.isnan(out["sd_cur_start_5m_A"][2]) and out["sd_cur_start_5m_B"][2] == pytest.approx(-5.0)
    # null entry -> every distance NULL (never imputed)
    assert out.loc[3, ["sd_cur_start_5m_A", "sd_cur_start_5m_B", "ad_cur_start_5m_A", "ad_cur_start_5m_B"]].isna().all()


def test_direction_dependent_level_choice_and_position(atlas_like):
    cols = [{"name": "cur_mfe_5m", "expr": "where(dir_5m == 1, highest_high_5m, lowest_low_5m)"},
            {"name": "cur_mae_5m", "expr": "where(dir_5m == 1, lowest_low_5m, highest_high_5m)"},
            {"name": "cur_pos_5m", "expr": "(executable_entry_price - cur_mae_5m) / (cur_mfe_5m - cur_mae_5m)"}]
    out = derive(atlas_like, cols)["frame"]
    assert out["cur_mfe_5m"].tolist()[:3] == [15_030.0, 15_030.0, 14_990.0]
    assert out["cur_mae_5m"].tolist()[:3] == [14_990.0, 14_990.0, 15_040.0]
    assert out["cur_pos_5m"][0] == pytest.approx(20 / 40)
    assert out["cur_pos_5m"][2] == pytest.approx((15_000 - 15_040) / (14_990 - 15_040))   # short-regime orientation


def test_zero_denominator_is_null_and_error_policy_refuses():
    f = pd.DataFrame({"a": [1.0, 0.0, -1.0, np.nan], "b": [0.0, 0.0, 2.0, 0.0]})
    out = derive(f, [{"name": "r", "expr": "a / b"}])
    assert out["frame"]["r"].isna().tolist() == [True, True, False, True]
    assert out["payload"]["columns"][0]["n_null"] == 3
    with pytest.raises(AnalysisOpError, match="DIVIDE_BY_ZERO"):
        derive(f, [{"name": "r", "expr": "a / b"}], div_zero="error")


def test_zero_span_position_is_null_with_category():
    f = pd.DataFrame({"E": [10.0, 10.0], "mfe": [12.0, 10.0], "mae": [8.0, 10.0]})
    out = derive(f, [{"name": "pos", "expr": "(E - mae) / (mfe - mae)"},
                     {"name": "pos_b", "expr": "where(mfe == mae, 'ZERO_SPAN', cut(pos, [0, 0.2, 0.4, 0.6, 0.8, 1.0000001], "
                                               "['<0', '[0,0.20)', '[0.20,0.40)', '[0.40,0.60)', '[0.60,0.80)', '[0.80,1.00]', '>1']))"}])["frame"]
    assert out["pos"][0] == 0.5 and math.isnan(out["pos"][1])
    assert out["pos_b"].tolist() == ["[0.40,0.60)", "ZERO_SPAN"]


def test_null_propagation_everywhere():
    f = pd.DataFrame({"a": [np.nan, 1.0], "s": [None, "x"], "t": ["y", None]})
    out = derive(f, [{"name": "abs_a", "expr": "abs(a)"}, {"name": "sgn", "expr": "sign(a)"}, {"name": "cmp", "expr": "a > 0"},
                     {"name": "mn", "expr": "min(a, 5)"}, {"name": "cc", "expr": "concat(s, t)"}, {"name": "isn", "expr": "is_null(a)"},
                     {"name": "co", "expr": "coalesce(a, 7)"}, {"name": "sq", "expr": "sqrt(a - 2)"}])["frame"]
    assert math.isnan(out["abs_a"][0]) and math.isnan(out["sgn"][0]) and pd.isna(out["cmp"][0]) and math.isnan(out["mn"][0])
    assert out["cc"].tolist() == [None, None]
    assert out["isn"].tolist() == [True, False]
    assert out["co"].tolist() == [7.0, 1.0]
    assert out["sq"].isna().all()                 # sqrt of a negative is NULL


def test_three_valued_logic():
    f = pd.DataFrame({"p": pd.array([True, False, None, None], dtype="boolean"),
                      "q": pd.array([None, None, True, False], dtype="boolean")})
    out = derive(f, [{"name": "a", "expr": "p and q"}, {"name": "o", "expr": "p or q"}, {"name": "n", "expr": "not p"}])["frame"]
    assert [None if pd.isna(v) else bool(v) for v in out["a"]] == [None, False, None, False]
    assert [None if pd.isna(v) else bool(v) for v in out["o"]] == [True, None, True, None]
    assert [None if pd.isna(v) else bool(v) for v in out["n"]] == [False, True, None, None]


def test_column_comparisons():
    f = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [2.0, 2.0, 2.0], "s": ["L", "S", "L"]})
    out = derive(f, [{"name": "lt", "expr": "a < b"}, {"name": "le", "expr": "a <= b"}, {"name": "eq", "expr": "a == b"},
                     {"name": "ne", "expr": "a != b"}, {"name": "ge", "expr": "a >= b"}, {"name": "gt", "expr": "a > b"},
                     {"name": "seq", "expr": "s == 'L'"}])["frame"]
    assert out["lt"].tolist() == [True, False, False] and out["le"].tolist() == [True, True, False]
    assert out["eq"].tolist() == [False, True, False] and out["ne"].tolist() == [True, False, True]
    assert out["ge"].tolist() == [False, True, True] and out["gt"].tolist() == [False, False, True]
    assert out["seq"].tolist() == [True, False, True]


def test_milestone_before_terminal_is_strict_and_integer_exact(atlas_like):
    expr = ("fp_fav_1p00_disposition == 'POSITIVE' and "
            "(terminal_flip_ts - executable_entry_ts) / 1000000000 > fp_fav_1p00_resolution_seconds")
    out = derive(atlas_like, [{"name": "reached_fav_1p00", "expr": expr},
                              {"name": "flip_minus_entry_ns", "expr": "terminal_flip_ts - executable_entry_ts"}])["frame"]
    # t0: 300 s to the flip, touch at 120 s -> reached. t1: touch at 50 s, flip at 50 s -> SAME INSTANT, not reached.
    assert bool(out["reached_fav_1p00"][0]) is True
    assert bool(out["reached_fav_1p00"][1]) is False
    assert pd.isna(out["reached_fav_1p00"][2])        # no terminal flip: undefined here, never True by accident
    assert pd.isna(out["reached_fav_1p00"][3])
    assert str(out["flip_minus_entry_ns"].dtype) == "Int64" and out["flip_minus_entry_ns"][0] == 300 * NS


def test_first_passage_ordering_with_tie(atlas_like):
    out = derive(atlas_like, [{"name": "order", "expr":
        "where(is_null(fp_fav_1p00_resolution_seconds), 'NONE', where(is_null(fp_adv_0p50_resolution_seconds), 'FAV_FIRST', "
        "where(fp_fav_1p00_resolution_seconds < fp_adv_0p50_resolution_seconds, 'FAV_FIRST', "
        "where(fp_fav_1p00_resolution_seconds == fp_adv_0p50_resolution_seconds, 'TIE', 'ADV_FIRST'))))"}])["frame"]
    assert out["order"].tolist() == ["FAV_FIRST", "TIE", "FAV_FIRST", "NONE"]


def test_exact_mtf_state_key_and_fixed_edge_bucket(atlas_like):
    out = derive(atlas_like, [
        {"name": "mtf_state", "expr": "concat(where(dir_1m == 1, 'L', 'S'), '|', where(dir_5m == 1, 'L', 'S'))"},
        {"name": "sd", "expr": "dir_1m * (executable_entry_price - start_price_5m) / atr_entry_1m"},
        {"name": "sd_bucket", "expr": "cut(sd, [-2, -1, -0.5, 0, 0.5, 1, 2], "
                                      "['<-2', '[-2,-1)', '[-1,-0.5)', '[-0.5,0)', '[0,0.5)', '[0.5,1)', '[1,2)', '>=2'])"}])["frame"]
    assert out["mtf_state"].tolist() == ["L|L", "S|L", "L|S", "L|L"]
    assert out["sd"].tolist()[:3] == [2.0, -2.0, -5.0]
    assert out["sd_bucket"].tolist() == [">=2", "[-2,-1)", "<-2", None]     # left-closed edges; NULL stays NULL


def test_keep_filters_rows_and_counts(atlas_like):
    out = derive(atlas_like, [{"name": "one", "expr": "1"}], keep="checkpoint_index == 0")
    assert len(out["frame"]) == 3
    assert out["payload"]["keep"]["kept"] == 3 and out["payload"]["keep"]["dropped_false"] == 1


def test_later_column_reads_earlier_and_never_overwrites(atlas_like):
    out = derive(atlas_like, [{"name": "x", "expr": "atr_entry_1m * 2"}, {"name": "y", "expr": "x + 1"}])["frame"]
    assert out["y"].tolist() == [11.0, 11.0, 9.0, 11.0]
    with pytest.raises(AnalysisOpError, match="COLUMN_EXISTS"):
        derive(atlas_like, [{"name": "dir_1m", "expr": "1"}])


def test_unknown_column_and_function_refused(atlas_like):
    with pytest.raises(AnalysisOpError, match="COLUMN_UNKNOWN"):
        derive(atlas_like, [{"name": "x", "expr": "no_such_col + 1"}])
    with pytest.raises(AnalysisOpError, match="FUNCTION_UNKNOWN"):
        derive(atlas_like, [{"name": "x", "expr": "exp(dir_1m)"}])


@pytest.mark.parametrize("bad", ["__import__('os')", "a.b", "a; b", "lambda: 1", "a ** 2", "a if b else c", "a < b < c", "[1, 2]",
                                 "open('x')", "a[0]", "a == = b"])
def test_no_arbitrary_code(bad):
    with pytest.raises(ExpressionError):
        parse(bad)


def test_type_errors_are_refused():
    f = pd.DataFrame({"a": [1.0], "s": ["x"]})
    with pytest.raises(AnalysisOpError, match="DERIVE_TYPE"):
        derive(f, [{"name": "x", "expr": "a + s"}])
    with pytest.raises(AnalysisOpError, match="DERIVE_TYPE"):
        derive(f, [{"name": "x", "expr": "s < 'y'"}])


def test_cut_validation():
    for bad in ("cut(a, [1, 0], ['x', 'y', 'z'])", "cut(a, [0, 1], ['x', 'y'])", "cut(a, [], ['x'])", "cut(a, [0], ['x', 'x'])"):
        with pytest.raises(ExpressionError, match="CUT_INVALID"):
            parse(bad)


def test_template_expansion_is_deterministic_and_complete():
    cols = [{"name": "sd_{level}_{tf}_{X}", "expr": "d * (E - {level}_{tf}) / {X}_{tf}",
             "each": {"tf": ["5m", "15m", "1h"], "level": ["cur_start", "pri_mfe"], "X": ["A", "B"]}}]
    a = expand_columns(cols)
    b = expand_columns([{"each": dict(reversed(list(cols[0]["each"].items()))), "expr": cols[0]["expr"], "name": cols[0]["name"]}])
    assert a == b and len(a) == 12 and len({n for n, _ in a}) == 12
    with pytest.raises(ExpressionError, match="TEMPLATE_UNRESOLVED"):
        expand_columns([{"name": "x_{tf}", "expr": "a"}])


def test_configuration_is_canonical_and_hash_stable():
    a = parse("dir_1m * (executable_entry_price - start_price_5m) / frozen_atr_5m")
    b = parse("dir_1m*(executable_entry_price-start_price_5m)/frozen_atr_5m")
    assert canonical(a) == canonical(b)
    f = pd.DataFrame({"dir_1m": [1], "executable_entry_price": [2.0], "start_price_5m": [1.0], "frozen_atr_5m": [1.0]})
    p1 = derive(f, [{"name": "x", "expr": "dir_1m * (executable_entry_price - start_price_5m) / frozen_atr_5m"}])["payload"]
    p2 = derive(f, [{"name": "x", "expr": "dir_1m*(executable_entry_price-start_price_5m)/frozen_atr_5m"}])["payload"]
    assert p1["columns"][0]["definition_sha256"] == p2["columns"][0]["definition_sha256"]
    assert derive(f, [{"name": "x", "expr": "dir_1m * 2"}])["frame"].equals(derive(f, [{"name": "x", "expr": "dir_1m * 2"}])["frame"])


def test_static_check_refuses_unknown_columns_before_execution():
    errors, cols = static_check({"columns": [{"name": "x", "expr": "a + 1"}, {"name": "y", "expr": "x + zz"}]}, ["a"])
    assert any("zz" in e for e in errors) and cols == ["a", "x", "y"]
    errors, _ = static_check({"columns": [{"name": "a", "expr": "1"}]}, ["a"])
    assert any("COLUMN_EXISTS" in e for e in errors)
    errors, _ = static_check({"columns": [{"name": "x", "expr": "a"}], "keep": "nope == 1"}, ["a"])
    assert any("keep" in e for e in errors)
