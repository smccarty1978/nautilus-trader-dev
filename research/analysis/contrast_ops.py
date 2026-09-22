"""``analysis.contrast.nominate`` and ``analysis.replication.scorecard``.

Two study-agnostic operations for a discovery -> freeze -> replication design. The science is
entirely in declared parameters; nothing here hard-codes a minimum N, a threshold or a class.

``contrast.nominate`` (discovery period)
    For every declared parent cell (``parent_by``; ``[]`` = the pooled population), every declared
    child dimension and each of its child values, and every declared metric: the child mean, the
    parent mean, the rest-of-parent mean, and ``estimate = mean(child) - mean(rest_of_parent)``
    with its session-day-clustered CR1 SE / t interval -- the SAME estimator (per-row influence,
    ``G/(G-1)`` factor, ``G-1`` df) as ``analysis.uncertainty.clustered_mean`` differences, computed
    per dimension from cluster sums (``test_contrast_ops`` proves the two agree). Declared support
    gates decide which contrasts enter the test family;
    Benjamini-Hochberg runs over the WHOLE family; declared materiality gates (absolute and
    relative child-vs-parent difference, CI excludes 0, BH q) decide what is material; material
    contrasts with enough support become replication CLAIMS. The payload is the claim file: the
    contrast specification, the gates, the replication rules and every claim, all frozen together.
    It never ranks by profitability -- the output is in deterministic key order.

``replication.scorecard`` (replication period)
    Reads a committed claim file whose sha256 is pinned in the plan (a mismatch refuses to run),
    re-measures EVERY claim on the replication rows with the claim file's own contrast
    specification, and classifies each with the claim file's own ordered rules. The replication
    run cannot change a bucket (the bucket columns come from the same sealed plan steps), a
    threshold or a rule (they are read from the pinned file, not from parameters), cannot drop a
    claim (every claim yields exactly one output row, unclassifiable ones included) and cannot add
    one (only claims in the file are measured).
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from research.analysis.frame_common import cluster_keys as _cluster_keys, require_columns as _require, scalar as _scalar
from research.analysis.ops import AnalysisOpError

REPLICATION_PREDICATES = ("underpowered", "estimate_null", "same_sign", "opposite_sign", "ratio_ge_min",
                          "ratio_lt_min", "ci_excludes_zero", "ci_includes_zero")
_STAT_COLUMNS = ("child_mean", "parent_mean", "estimate", "se", "df", "ci_low", "ci_high", "n_child", "n_parent")


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _sha(obj: Any) -> str:
    return hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


def _label(v: Any) -> Optional[str]:
    """A child value as a parquet-safe string column (dimensions mix types across a family)."""
    return None if v is None else v if isinstance(v, str) else _canon(v)


def _sort_key(v: Any) -> Tuple[str, Any]:
    return (type(v).__name__, v)


# --------------------------------------------------------------------------- #
# Benjamini-Hochberg
# --------------------------------------------------------------------------- #
def benjamini_hochberg(p_values: Sequence[Optional[float]], *, null_policy: str = "count_as_one") -> List[Optional[float]]:
    """BH adjusted q-values, ``q_(i) = min_{j >= i} min(1, m / j * p_(j))`` over the ascending order.

    Deterministic and order-invariant: the q of a test depends only on the multiset of p-values,
    and tied p-values get the identical q. ``null_policy``: ``count_as_one`` (default,
    conservative) ranks a missing p as 1.0 -- it counts toward the family size m -- and reports
    its q as None; ``exclude`` drops it from the family (m counts only real p-values).
    """
    if null_policy not in ("count_as_one", "exclude"):
        raise AnalysisOpError(f"ANALYSIS_BH_NULL_POLICY_INVALID: {null_policy!r} (count_as_one | exclude)")
    vals: List[Tuple[float, int]] = []
    for i, p in enumerate(p_values):
        if p is None or (isinstance(p, float) and math.isnan(p)):
            if null_policy == "count_as_one":
                vals.append((1.0, i))
            continue
        p = float(p)
        if not (0.0 <= p <= 1.0):
            raise AnalysisOpError(f"ANALYSIS_BH_P_INVALID: p-value {p!r} outside [0, 1]")
        vals.append((p, i))
    m = len(vals)
    out: List[Optional[float]] = [None] * len(p_values)
    if m == 0:
        return out
    vals.sort(key=lambda t: t[0])                 # ties share a q, so their relative order is irrelevant
    q_sorted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        p, _ = vals[rank - 1]
        running = min(running, min(1.0, p * m / rank))
        q_sorted[rank - 1] = running
    for (p, i), q in zip(vals, q_sorted):
        orig = p_values[i]
        if orig is None or (isinstance(orig, float) and math.isnan(orig)):
            continue                              # count_as_one: occupies a rank, reports no q
        out[i] = q
    return out


# --------------------------------------------------------------------------- #
# shared contrast statistics (the clustered_mean difference estimator, vectorised per dimension)
# --------------------------------------------------------------------------- #
def _t_quantiles(df: int, confidence: float) -> float:
    from scipy import stats
    return float(stats.t.ppf((1.0 + confidence) / 2.0, df))


def _p_value(est: Optional[float], se: Optional[float], df: Optional[int]) -> Optional[float]:
    if est is None or se is None or df is None or not (se > 0.0):
        return None
    from scipy import stats
    return float(2.0 * stats.t.sf(abs(est / se), df))


def _dimension_stats(sub: pd.DataFrame, dimension: str, metric: str, *, confidence: float,
                     child_values: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    """Child vs rest-of-parent contrasts for every child value of ``dimension`` inside one parent.

    ``sub`` is the parent's NON-censored rows (with ``__cluster__``). Usable rows for the metric are
    those with a non-null metric value and a non-null cluster. The difference and its CR1 SE are
    exactly ``clustered_uncertainty``'s: psi = (y-mean_a)/n_a on the child, -(y-mean_b)/n_b on the
    rest; cluster sums over every cluster present among the parent's usable rows.
    """
    y_all = pd.to_numeric(sub[metric], errors="coerce")
    ok = (y_all.notna() & sub["__cluster__"].notna()).to_numpy()
    u = sub[ok]
    y = y_all[ok].to_numpy(dtype="float64")
    codes, uniques = pd.factorize(u["__cluster__"], sort=True)
    G = int(len(uniques))
    dim_all = sub[dimension]
    n_parent, n_parent_rows = int(len(u)), int(len(sub))
    parent_mean = float(y.mean()) if n_parent else None
    tot_s = np.bincount(codes, weights=y, minlength=G) if G else np.zeros(0)
    tot_n = np.bincount(codes, minlength=G).astype("float64") if G else np.zeros(0)
    if child_values is None:
        child_values = sorted({_scalar(v) for v in dim_all.dropna().tolist()}, key=_sort_key)
    tcrit = _t_quantiles(G - 1, confidence) if G >= 2 else None
    out: List[Dict[str, Any]] = []
    for c in child_values:
        a = u[dimension].eq(c).fillna(False).to_numpy(dtype=bool)
        na = int(a.sum())
        nb = n_parent - na
        n_child_rows = int(dim_all.eq(c).fillna(False).sum())
        st: Dict[str, Any] = {"child_value": c, "n_child": na, "n_rest": nb, "n_parent": n_parent,
                              "n_child_rows": n_child_rows, "n_parent_rows": n_parent_rows, "n_clusters": G,
                              "parent_mean": parent_mean, "child_mean": None, "rest_mean": None, "estimate": None,
                              "se": None, "df": None, "ci_low": None, "ci_high": None}
        if na > 0:
            st["child_mean"] = float(y[a].mean())
        if nb > 0:
            st["rest_mean"] = float(y[~a].mean())
        if na > 0 and nb > 0:
            ma, mb = st["child_mean"], st["rest_mean"]
            est = ma - mb
            st["estimate"] = est
            if G >= 2:
                sa = np.bincount(codes[a], weights=y[a], minlength=G)
                ca = np.bincount(codes[a], minlength=G).astype("float64")
                S = (sa - ca * ma) / na - ((tot_s - sa) - (tot_n - ca) * mb) / nb
                se = math.sqrt((G / (G - 1)) * float((S ** 2).sum()))
                st.update({"se": se, "df": G - 1, "ci_low": est - tcrit * se, "ci_high": est + tcrit * se})
        out.append(st)
    return out


def _prepare(rows: pd.DataFrame, *, cluster_column: Optional[str], cluster_ts_column: Optional[str],
             censored_column: Optional[str], where: str) -> pd.DataFrame:
    work = rows.assign(__cluster__=_cluster_keys(rows, cluster_column, cluster_ts_column, where))
    if censored_column is not None:
        _require(work, [censored_column], where)
        work = work[~work[censored_column].fillna(False).astype(bool).to_numpy()]
    return work


def _parents(work: pd.DataFrame, parent_by: Sequence[str]) -> List[Tuple[Dict[str, Any], pd.DataFrame]]:
    keys = list(parent_by)
    if not keys:
        return [({}, work)]
    out = []
    for vals, sub in work.groupby(keys, dropna=False, sort=True):
        vals = vals if isinstance(vals, tuple) else (vals,)
        out.append(({k: _scalar(v) for k, v in zip(keys, vals)}, sub))
    return out


def _contrast_blocks(contrasts: Optional[Sequence[Mapping[str, Any]]], parent_by: Sequence[str], dimensions: Sequence[str],
                     mode: str, where: str) -> List[Dict[str, List[str]]]:
    if mode != "compute":
        return []
    if contrasts is not None:
        if list(parent_by) or list(dimensions):
            raise AnalysisOpError(f"ANALYSIS_CONTRAST_SPEC_AMBIGUOUS: {where} declares both contrasts and parent_by/dimensions")
        raw = list(contrasts)
    else:
        raw = [{"parent_by": list(parent_by), "dimensions": list(dimensions)}]
    blocks = []
    for i, b in enumerate(raw):
        if not isinstance(b, Mapping) or set(b) - {"parent_by", "dimensions"}:
            raise AnalysisOpError(f"ANALYSIS_CONTRAST_SPEC_INVALID: {where} contrasts[{i}] takes parent_by and dimensions")
        dims = [str(d) for d in (b.get("dimensions") or [])]
        if not dims:
            raise AnalysisOpError(f"ANALYSIS_CONTRAST_DIMENSIONS_MISSING: {where} contrasts[{i}] declares no dimensions")
        pb = [str(p) for p in (b.get("parent_by") or [])]
        if set(pb) & set(dims):
            raise AnalysisOpError(f"ANALYSIS_CONTRAST_SPEC_INVALID: {where} contrasts[{i}] uses a column as both parent and child")
        blocks.append({"parent_by": pb, "dimensions": dims})
    return blocks


def _metrics(metrics: Sequence[Any]) -> List[str]:
    out = []
    for m in metrics:
        out.append(str(m["column"]) if isinstance(m, Mapping) else str(m))
    if not out or len(set(out)) != len(out):
        raise AnalysisOpError(f"ANALYSIS_CONTRAST_METRICS_INVALID: declare distinct metric columns, got {out}")
    return out


def _validate_replication(rep: Mapping[str, Any], where: str) -> Dict[str, Any]:
    need = {"min_ratio", "min_child_n", "rules"}
    if not isinstance(rep, Mapping) or not need <= set(rep):
        raise AnalysisOpError(f"ANALYSIS_REPLICATION_RULES_INVALID: {where} needs {sorted(need)}")
    rules = rep["rules"]
    if not isinstance(rules, (list, tuple)) or not rules:
        raise AnalysisOpError(f"ANALYSIS_REPLICATION_RULES_INVALID: {where}.rules must be a non-empty ordered list")
    for i, r in enumerate(rules):
        if not isinstance(r, Mapping) or not r.get("class") or not isinstance(r.get("requires"), (list, tuple)) or not r["requires"]:
            raise AnalysisOpError(f"ANALYSIS_REPLICATION_RULES_INVALID: {where}.rules[{i}] needs class and a non-empty requires")
        bad = [p for p in r["requires"] if p not in REPLICATION_PREDICATES]
        if bad:
            raise AnalysisOpError(f"ANALYSIS_REPLICATION_RULES_INVALID: {where}.rules[{i}] unknown predicates {bad}; "
                                  f"known {list(REPLICATION_PREDICATES)}")
    return {"min_ratio": float(rep["min_ratio"]), "min_child_n": int(rep["min_child_n"]),
            "rules": [{"class": str(r["class"]), "requires": [str(p) for p in r["requires"]]} for r in rules],
            "fallback": str(rep.get("fallback", "UNCLASSIFIED"))}


def _claim_id(parent: Mapping[str, Any], dimension: str, child_value: Any, metric: str) -> str:
    return "C" + _sha({"parent": dict(parent), "dimension": dimension, "child_value": child_value, "metric": metric})[:16]


# --------------------------------------------------------------------------- #
# analysis.contrast.nominate
# --------------------------------------------------------------------------- #
def contrast_nominate(rows: pd.DataFrame, *, gates: Mapping[str, Any], materiality: Mapping[str, Any],
                      mode: str = "compute", parent_by: Sequence[str] = (), dimensions: Sequence[str] = (),
                      metrics: Sequence[Any] = (), cluster_column: Optional[str] = None,
                      cluster_ts_column: Optional[str] = None, censored_column: Optional[str] = None,
                      exclude_child_values: Sequence[Any] = (), n_basis: str = "metric", confidence: float = 0.95,
                      bh_null_policy: str = "count_as_one", key_columns: Sequence[str] = (),
                      replication: Optional[Mapping[str, Any]] = None,
                      contrasts: Optional[Sequence[Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """Apply frozen nomination rules to parent/child contrasts (see the module docstring).

    ``gates``: ``{min_child_n, min_parent_n, min_nominate_n}`` (support basis ``n_basis``: ``metric`` =
    usable metric values, ``rows`` = non-censored rows). ``materiality``: ``{min_abs_difference,
    min_relative_difference, require_ci_excludes_zero, max_bh_q, relative_when_parent_zero}``, each
    optional except ``max_bh_q``; the absolute/relative differences are child vs the WHOLE parent, the
    CI is on child minus rest-of-parent. ``mode: precomputed`` gates a statistics frame that already
    carries ``key_columns`` + ``child_mean parent_mean estimate se df ci_low ci_high n_child n_parent``
    (``p_value`` optional) instead of computing it.

    ``contrasts: [{parent_by, dimensions}, ...]`` declares several parent specifications (e.g. every
    exact state vs the pooled population AND every structural bucket vs its exact state) whose
    contrasts form ONE Benjamini-Hochberg family; it replaces the top-level ``parent_by`` /
    ``dimensions``, never combines with them.
    """
    where = "contrast.nominate"
    if mode not in ("compute", "precomputed"):
        raise AnalysisOpError(f"ANALYSIS_CONTRAST_MODE_INVALID: {mode!r} (compute | precomputed)")
    if n_basis not in ("metric", "rows"):
        raise AnalysisOpError(f"ANALYSIS_CONTRAST_N_BASIS_INVALID: {n_basis!r} (metric | rows)")
    if not (0.0 < float(confidence) < 1.0):
        raise AnalysisOpError(f"ANALYSIS_CONTRAST_CONFIDENCE_INVALID: {confidence!r}")
    g = {k: int(gates[k]) for k in ("min_child_n", "min_parent_n", "min_nominate_n") if k in gates}
    if set(g) != {"min_child_n", "min_parent_n", "min_nominate_n"}:
        raise AnalysisOpError(f"ANALYSIS_CONTRAST_GATES_INVALID: gates needs min_child_n, min_parent_n, min_nominate_n; got {sorted(gates)}")
    mat = dict(materiality or {})
    if "max_bh_q" not in mat:
        raise AnalysisOpError("ANALYSIS_CONTRAST_MATERIALITY_INVALID: materiality.max_bh_q is required (the multiple-comparison gate)")
    unknown = set(mat) - {"min_abs_difference", "min_relative_difference", "require_ci_excludes_zero", "max_bh_q",
                          "relative_when_parent_zero"}
    if unknown:
        raise AnalysisOpError(f"ANALYSIS_CONTRAST_MATERIALITY_INVALID: unknown keys {sorted(unknown)}")
    rel_zero = str(mat.get("relative_when_parent_zero", "fail"))
    if rel_zero not in ("fail", "pass"):
        raise AnalysisOpError(f"ANALYSIS_CONTRAST_MATERIALITY_INVALID: relative_when_parent_zero {rel_zero!r} (fail | pass)")
    rep = _validate_replication(replication, f"{where}.replication") if replication is not None else None
    excluded = {_canon(v) for v in exclude_child_values}

    blocks = _contrast_blocks(contrasts, parent_by, dimensions, mode, where)
    tests: List[Dict[str, Any]] = []
    if mode == "compute":
        mets = _metrics(metrics)
        _require(rows, sorted({c for b in blocks for c in b["parent_by"] + b["dimensions"]} | set(mets)), where)
        work = _prepare(rows, cluster_column=cluster_column, cluster_ts_column=cluster_ts_column,
                        censored_column=censored_column, where=where)
        for block in blocks:
            for parent, sub in _parents(work, block["parent_by"]):
                for dim in block["dimensions"]:
                    for m in mets:
                        for st in _dimension_stats(sub, dim, m, confidence=float(confidence)):
                            if _canon(st["child_value"]) in excluded:
                                continue
                            tests.append({"parent": parent, "parent_by": list(block["parent_by"]), "dimension": dim,
                                          "metric": m, **st})
    else:
        keys = [str(k) for k in key_columns]
        if not keys:
            raise AnalysisOpError(f"ANALYSIS_CONTRAST_KEYS_MISSING: {where} mode: precomputed needs key_columns")
        _require(rows, keys + list(_STAT_COLUMNS), where)
        for _, r in rows.iterrows():
            st = {c: _scalar(r[c]) for c in _STAT_COLUMNS}
            st["df"] = int(st["df"]) if st["df"] is not None else None
            key = {k: _scalar(r[k]) for k in keys}
            tests.append({"parent": key, "parent_by": keys, "dimension": None, "metric": None, "child_value": None,
                          "n_child_rows": st["n_child"], "n_parent_rows": st["n_parent"], "rest_mean": None,
                          "n_rest": None, "n_clusters": None,
                          "p_value_in": (_scalar(r["p_value"]) if "p_value" in rows.columns else None), **st})

    # support gates -> the test family
    for t in tests:
        nc = t["n_child"] if n_basis == "metric" else t["n_child_rows"]
        npar = t["n_parent"] if n_basis == "metric" else t["n_parent_rows"]
        t["support_child"], t["support_parent"] = nc, npar
        reason = None
        if nc is None or nc < g["min_child_n"]:
            reason = "CHILD_N_BELOW_MIN"
        elif npar is None or npar < g["min_parent_n"]:
            reason = "PARENT_N_BELOW_MIN"
        elif t.get("n_rest") == 0:
            reason = "NO_REST_OF_PARENT"
        t["tested"] = reason is None
        t["not_tested_reason"] = reason
        p_in = t.pop("p_value_in", None)
        t["p_value"] = (p_in if p_in is not None else _p_value(t["estimate"], t["se"], t["df"])) if t["tested"] else None
    family = [t for t in tests if t["tested"]]
    qs = benjamini_hochberg([t["p_value"] for t in family], null_policy=bh_null_policy)
    for t, q in zip(family, qs):
        t["q_value"] = q
    for t in tests:
        t.setdefault("q_value", None)
        cm, pm, est = t["child_mean"], t["parent_mean"], t["estimate"]
        diff = (cm - pm) if (cm is not None and pm is not None) else None
        t["diff_vs_parent"] = diff
        if diff is None:
            rel = None
        elif pm == 0:
            rel = None if diff == 0 else math.inf
        else:
            rel = abs(diff) / abs(pm)
        t["relative_diff"] = rel if (rel is None or math.isfinite(rel)) else None
        flags = {}
        if "min_abs_difference" in mat:
            flags["pass_abs"] = diff is not None and abs(diff) >= float(mat["min_abs_difference"])
        if "min_relative_difference" in mat:
            if rel is not None and math.isinf(rel):
                flags["pass_rel"] = rel_zero == "pass"
            else:
                flags["pass_rel"] = rel is not None and rel >= float(mat["min_relative_difference"])
        if bool(mat.get("require_ci_excludes_zero", False)):
            lo, hi = t["ci_low"], t["ci_high"]
            flags["pass_ci"] = lo is not None and hi is not None and (lo > 0.0 or hi < 0.0)
        flags["pass_q"] = t["q_value"] is not None and t["q_value"] <= float(mat["max_bh_q"])
        t.update(flags)
        t["material"] = bool(t["tested"] and all(flags.values()))
        t["claim_eligible"] = bool(t["material"] and t["support_child"] is not None and t["support_child"] >= g["min_nominate_n"])
        t["claim_id"] = _claim_id(t["parent"], t["dimension"], t["child_value"], t["metric"]) if mode == "compute" else \
            "C" + _sha(t["parent"])[:16]
    cell_material: Dict[str, bool] = {}
    for t in tests:
        ck = _canon([t["parent"], t["dimension"], t["child_value"]])
        cell_material[ck] = cell_material.get(ck, False) or t["material"]
    tests.sort(key=lambda t: _canon([t["parent"], t["dimension"], t["child_value"], t["metric"]]))

    claims = []
    for t in tests:
        if not t["claim_eligible"]:
            continue
        claims.append({"claim_id": t["claim_id"], "parent": t["parent"], "parent_by": t["parent_by"], "dimension": t["dimension"],
                       "child_value": t["child_value"], "metric": t["metric"],
                       "expected_direction": (1 if t["estimate"] > 0 else -1 if t["estimate"] < 0 else 0),
                       "discovery": {k: t[k] for k in ("estimate", "se", "df", "ci_low", "ci_high", "child_mean", "parent_mean",
                                                       "rest_mean", "diff_vs_parent", "relative_diff", "p_value", "q_value",
                                                       "n_child", "n_parent", "n_child_rows", "n_parent_rows", "n_clusters")}})
    spec = {"mode": mode, "contrasts": blocks,
            "metrics": (_metrics(metrics) if mode == "compute" else []), "cluster_column": cluster_column,
            "cluster_ts_column": cluster_ts_column, "censored_column": censored_column,
            "exclude_child_values": list(exclude_child_values), "n_basis": n_basis, "confidence": float(confidence)}
    frozen = {"contrast_spec": spec, "gates": g, "materiality": mat, "bh_null_policy": bh_null_policy, "replication": rep}
    payload = {
        "schema_version": 1, "kind": "analysis.contrast.nominate", **frozen,
        "specification_sha256": _sha(frozen),
        "summary": {"n_contrasts": len(tests), "n_cells": len(cell_material),
                    "n_parents": len({_canon(t["parent"]) for t in tests}),
                    "family_size": len(family) if bh_null_policy == "count_as_one" else sum(t["p_value"] is not None for t in family),
                    "n_tested": len(family), "n_not_tested": len(tests) - len(family),
                    "not_tested_reasons": {r: sum(t["not_tested_reason"] == r for t in tests)
                                           for r in sorted({t["not_tested_reason"] for t in tests if t["not_tested_reason"]})},
                    "n_material": sum(t["material"] for t in tests),
                    "n_material_cells": sum(cell_material.values()), "n_claims": len(claims)},
        "claims": claims,
    }
    frame = pd.DataFrame([{**{f"parent.{k}": v for k, v in t["parent"].items()}, "parent_key": _canon(t["parent"]),
                           **{k: v for k, v in t.items() if k not in ("parent", "parent_by")},
                           "parent_by": _canon(t["parent_by"]), "child_value": _label(t["child_value"])}
                          for t in tests])
    return {"frame": frame, "payload": payload}


# --------------------------------------------------------------------------- #
# analysis.replication.scorecard
# --------------------------------------------------------------------------- #
def _classify(pred: Mapping[str, bool], rules: Sequence[Mapping[str, Any]], fallback: str) -> Tuple[str, str]:
    for i, r in enumerate(rules):
        if all(pred[p] for p in r["requires"]):
            return r["class"], f"rules[{i}]: " + " and ".join(r["requires"])
    true = [p for p in REPLICATION_PREDICATES if pred[p]]
    return fallback, "no rule matched; true predicates: " + (", ".join(true) or "none")


def replication_scorecard(rows: pd.DataFrame, *, claims_path: str, claims_sha256: str,
                          context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Classify every frozen claim on the replication rows (see the module docstring).

    ``claims_path`` is relative to the study directory and must stay inside it; ``claims_sha256`` is
    the sha256 of the file's bytes as committed. Everything else -- contrast specification, support
    basis, confidence, ratio, minimum N and the ordered classification rules -- comes from the file.
    """
    where = "replication.scorecard"
    ctx = dict(context or {})
    rel = Path(str(claims_path))
    if rel.is_absolute() or ".." in rel.parts:
        raise AnalysisOpError(f"ANALYSIS_REPLICATION_CLAIMS_PATH_INVALID: {claims_path!r} must be relative to the study directory")
    base = Path(ctx.get("study_dir") or ".")
    path = base / rel
    if not path.is_file():
        raise AnalysisOpError(f"ANALYSIS_REPLICATION_CLAIMS_MISSING: {path}")
    data = path.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != str(claims_sha256).lower():
        raise AnalysisOpError(f"ANALYSIS_REPLICATION_CLAIMS_HASH_MISMATCH: {claims_path} sha256 {actual} != pinned {claims_sha256}; "
                              "the frozen claim file changed after it was committed")
    doc = json.loads(data.decode("utf-8"))
    if doc.get("kind") != "analysis.contrast.nominate" or "claims" not in doc or "contrast_spec" not in doc:
        raise AnalysisOpError(f"ANALYSIS_REPLICATION_CLAIMS_INVALID: {claims_path} is not a contrast.nominate claim file")
    if doc.get("replication") is None:
        raise AnalysisOpError(f"ANALYSIS_REPLICATION_RULES_MISSING: {claims_path} froze no replication rules")
    rep = _validate_replication(doc["replication"], f"{claims_path}.replication")
    spec = doc["contrast_spec"]
    if spec.get("mode") != "compute":
        raise AnalysisOpError("ANALYSIS_REPLICATION_CLAIMS_INVALID: only claims nominated in mode: compute can be re-measured")
    claims = list(doc["claims"])
    ids = [c["claim_id"] for c in claims]
    if len(set(ids)) != len(ids):
        raise AnalysisOpError("ANALYSIS_REPLICATION_CLAIMS_INVALID: duplicate claim ids")
    needed = sorted({p for c in claims for p in c["parent_by"]} | {c["dimension"] for c in claims} | {c["metric"] for c in claims})
    _require(rows, needed, where)                  # a missing column is an error, never a dropped claim
    work = _prepare(rows, cluster_column=spec.get("cluster_column"), cluster_ts_column=spec.get("cluster_ts_column"),
                    censored_column=spec.get("censored_column"), where=where)
    by_spec: Dict[str, Dict[str, pd.DataFrame]] = {}
    empty = work.iloc[0:0]
    out: List[Dict[str, Any]] = []
    for c in claims:
        pk = _canon(c["parent_by"])
        if pk not in by_spec:
            by_spec[pk] = {_canon(k): sub for k, sub in _parents(work, c["parent_by"])}
        sub = by_spec[pk].get(_canon(c["parent"]), empty)
        (st,) = _dimension_stats(sub, c["dimension"], c["metric"], confidence=float(spec["confidence"]),
                                 child_values=[c["child_value"]])
        disc = c["discovery"]["estimate"]
        rep_est = st["estimate"]
        support = st["n_child"] if spec["n_basis"] == "metric" else st["n_child_rows"]
        lo, hi = st["ci_low"], st["ci_high"]
        s_disc = (disc > 0) - (disc < 0)
        s_rep = ((rep_est > 0) - (rep_est < 0)) if rep_est is not None else 0
        ratio = (abs(rep_est) / abs(disc)) if (rep_est is not None and disc) else None
        pred = {
            "underpowered": support < rep["min_child_n"],
            "estimate_null": rep_est is None,
            "same_sign": rep_est is not None and s_rep != 0 and s_rep == s_disc,
            "opposite_sign": rep_est is not None and s_rep != 0 and s_rep == -s_disc,
            "ratio_ge_min": ratio is not None and ratio >= rep["min_ratio"],
            "ratio_lt_min": ratio is not None and ratio < rep["min_ratio"],
            "ci_excludes_zero": lo is not None and hi is not None and (lo > 0.0 or hi < 0.0),
            "ci_includes_zero": lo is not None and hi is not None and lo <= 0.0 <= hi,
        }
        cls, reason = _classify(pred, rep["rules"], rep["fallback"])
        out.append({"claim_id": c["claim_id"], "parent_key": _canon(c["parent"]), "dimension": c["dimension"],
                    "child_value": c["child_value"], "metric": c["metric"], "expected_direction": c["expected_direction"],
                    "discovery_value": disc, "discovery_ci_low": c["discovery"]["ci_low"], "discovery_ci_high": c["discovery"]["ci_high"],
                    "replication_value": rep_est, "replication_ci_low": lo, "replication_ci_high": hi,
                    "replication_se": st["se"], "replication_df": st["df"], "replication_child_mean": st["child_mean"],
                    "replication_parent_mean": st["parent_mean"], "support": support, "n_child": st["n_child"],
                    "n_parent": st["n_parent"], "n_clusters": st["n_clusters"], "ratio": ratio,
                    **{f"pred.{k}": v for k, v in pred.items()}, "classification": cls, "reason": reason})
    if len(out) != len(claims):          # structural: every claim yields exactly one row
        raise AnalysisOpError("ANALYSIS_REPLICATION_CLAIM_DROPPED")
    classes = [r["class"] for r in rep["rules"]] + [rep["fallback"]]
    payload = {"schema_version": 1, "kind": "analysis.replication.scorecard", "claims_path": str(claims_path),
               "claims_sha256": actual, "specification_sha256": doc.get("specification_sha256"),
               "contrast_spec": spec, "replication": rep, "n_claims": len(claims),
               "counts": {k: sum(r["classification"] == k for r in out) for k in dict.fromkeys(classes)},
               "rows": out}
    frame = pd.DataFrame([{**r, "child_value": _label(r["child_value"])} for r in out])
    return {"frame": frame, "payload": payload}


__all__ = ["benjamini_hochberg", "contrast_nominate", "replication_scorecard", "REPLICATION_PREDICATES"]
