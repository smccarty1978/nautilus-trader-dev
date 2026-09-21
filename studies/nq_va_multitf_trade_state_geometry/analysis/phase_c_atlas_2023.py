"""Phase C -- 2023 DESCRIPTIVE LIFECYCLE ATLAS (discovery year only).

Reads ONLY the sealed v4 2023 TRAIN partition (hash-verified against its manifest) and writes the
artifacts/phase_c_2023_* tables. Nothing is fitted, tuned or optimised; every bucket edge is a
2023 quantile or a milestone rung of the COLLECTED ladder, and is frozen into the atlas spec so
2024 can be read with the same edges.

This is a descriptive study-local reader, not a platform capability. The registered analysis_ops
cannot express most of these tables; see ANALYSIS_HARNESS_GAPS below (recorded in the report).

Coordinates (all price distances are ATR-normalised; denominators are named in the column):
  A      = atr_entry_1m  (1m Wilder ATR frozen at the confirmed 1m flip; the outcome contract ATR)
  E      = executable entry fill of the T0 row (next 1s open after T0 = flip-bar close + 15 s)
  s      = seconds since E. Checkpoint k is at s = 15k (k = 0..19).
  lifecycle = E -> the next confirmed opposite 1m flip (TRADING_DAY, truncate).
  A milestone is IN-LIFECYCLE iff its first passage (seconds from E) <= time from E to the flip.
  The arms keep running after the flip (own 24 h horizon), so for every resolved terminal the
  in-lifecycle status of every rung is fully observed -- no censoring inside the lifecycle.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

STUDY = Path(__file__).resolve().parents[1]
PARTS = STUDY / "_work" / "controller" / "partitions" / "train"
OUT = STUDY / "artifacts"
EXPECT = {
    "plan_sha256": "11fcaf24a18e3c3f442e8a589a962f3cff6f075810fb136f14ac1b4720d1e557",
    "composite_seal_hash": "ba69ad0b29b0ef76fba6aa12e8ee72f5a9a41a49f74e8b0d51628738921f1ec1",
    "execution_manifest_sha256": "c9249f99ff96ab5b1dd8ae7f0876f490f6e1f9e3238fe4b7ae9cd71150748356",
    "year": 2023,
}
FAV = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00, 4.00, 5.00]
ADV = [0.25, 0.50, 0.75, 1.00, 1.50, 2.00, 3.00]
TFS = ["5m", "15m", "1h"]
MIN_N = 100          # a cell with fewer trades is reported with N only
MIN_N_HIER = 150     # hierarchical (section 6) cells
FLAT = 0.25          # near-flat band = the smallest collected rung
CHECK_S = [15, 30, 45, 60, 90, 120, 180, 240, 285]
INC_S = [15, 30, 60, 120, 300, 600, 1200, 1800, 3600]


def tag(x: float) -> str:
    return f"{x:.2f}".replace(".", "p")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def jdump(name: str, obj) -> None:
    def default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if not np.isfinite(o) else float(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return str(o)

    def clean(o):
        if isinstance(o, float) and not np.isfinite(o):
            return None
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        return o

    (OUT / name).write_text(json.dumps(clean(obj), indent=1, default=default), encoding="utf-8")


# ----------------------------------------------------------------------------------------------
# 0. Frame identity -- refuse anything but the sealed 2023 partition
# ----------------------------------------------------------------------------------------------
def load_frame(year: int = 2023):
    """year != 2023 is only reachable through replication_readout.py, which refuses 2024 until the
    replication contract is committed."""
    PART = PARTS / str(year)
    man = json.loads((PART / "manifest.json").read_text(encoding="utf-8"))
    for k, v in {**EXPECT, "year": year}.items():
        if man.get(k) != v:
            sys.exit(f"FRAME_IDENTITY_MISMATCH {k}: {man.get(k)} != {v}")
    obs_p, cand_p = PART / "observations.parquet", PART / "candidates.parquet"
    got = {"observations_sha256": sha256(obs_p), "candidates_sha256": sha256(cand_p)}
    for k, v in got.items():
        if man[k] != v:
            sys.exit(f"FRAME_HASH_MISMATCH {k}")
    o, c = pd.read_parquet(obs_p), pd.read_parquet(cand_p)
    key = ["observation_ts", "regime_start_ns", "checkpoint_index"]
    m = o.merge(c, on=key, how="inner", validate="1:1")
    if len(m) != len(o):
        sys.exit("FRAME_JOIN_LOSS")
    yrs = pd.to_datetime(m.regime_start_ns, utc=True).dt.tz_convert("America/Chicago").dt.year
    if set(yrs.unique()) != {year}:
        sys.exit(f"OFF_YEAR_ROWS {sorted(yrs.unique())}")
    ident = {**{k: man[k] for k in EXPECT}, **got, "rows": len(m), "partition": str(PART.relative_to(STUDY))}
    return m, ident


# ----------------------------------------------------------------------------------------------
# 1. Trade table (T0 rows) with lifecycle-bounded ladder
# ----------------------------------------------------------------------------------------------
def lifecycle_ladder(df: pd.DataFrame) -> pd.DataFrame:
    """In-lifecycle first-passage seconds per rung (inf = not reached inside the lifecycle)."""
    D = (df.terminal_flip_ts - df.terminal_entry_ts) / 1e9
    out = pd.DataFrame(index=df.index)
    out["life_s"] = D
    for x in FAV:
        a = f"fp_fav_{tag(x)}"
        hit = (df[a + "_disposition"] == "POSITIVE") & (df[a + "_resolution_seconds"] <= D)
        out[f"tf_{tag(x)}"] = np.where(hit, df[a + "_resolution_seconds"], np.inf)
    for x in ADV:
        a = f"fp_adv_{tag(x)}"
        hit = (df[a + "_disposition"] == "NEGATIVE") & (df[a + "_resolution_seconds"] <= D)
        out[f"ta_{tag(x)}"] = np.where(hit, df[a + "_resolution_seconds"], np.inf)
    return out


def rung_max(lad: pd.DataFrame, side: str, levels, by_s=None) -> pd.Series:
    r = pd.Series(0.0, index=lad.index)
    for x in levels:
        t = lad[f"{side}_{tag(x)}"]
        ok = np.isfinite(t) if by_s is None else (t <= by_s)
        r = r.where(~ok, x)
    return r


def build_trades(m: pd.DataFrame):
    t = m[m.checkpoint_index == 0].copy()
    t["resolved"] = (t.terminal_flip_disposition == "LABELED_POSITIVE") & t.terminal_gross_pnl_atr.notna()
    excluded = t.loc[~t.resolved, ["regime_start_ns", "terminal_flip_disposition", "terminal_flip_censor_reason",
                                   "terminal_exit_unavailable_reason"]]
    t = t[t.resolved].copy()
    t["A"] = t.atr_entry_1m
    t["P0"] = t.terminal_entry_price
    t["pnl"] = t.terminal_gross_pnl_atr
    t["dur"] = t.terminal_duration_seconds
    ct = pd.to_datetime(t.regime_start_ns, utc=True).dt.tz_convert("America/Chicago")
    t["day"] = ct.dt.strftime("%Y-%m-%d")
    t["month"] = ct.dt.month
    t["ct_hour"] = ct.dt.hour + ct.dt.minute / 60.0
    t["side"] = np.where(t.dir_1m > 0, "LONG", "SHORT")
    lad = lifecycle_ladder(t)
    t = pd.concat([t, lad], axis=1)
    t["mfe_rung"] = rung_max(lad, "tf", FAV)
    t["mae_rung"] = rung_max(lad, "ta", ADV)
    # --- 1m own state at T0 (flip-bar anchored, then re-anchored to E)
    t["entry_ext_A"] = t.dir_1m * (t.P0 - t.start_price_1m) / t.A          # E vs flip-bar open
    t["flipbar_mfe_A"] = t.mfe_atr_1m                                      # flip-bar-open anchored
    t["flipbar_mae_A"] = t.mae_atr_1m
    t["atr_ratio_1m_now_vs_frozen"] = t.atr_1m / t.A
    t["A_points"] = t.A
    # --- multi-timeframe direction relative to the new 1m flip
    for h in TFS:
        t[f"rel_{h}"] = np.where(t[f"dir_{h}"] * t.dir_1m > 0, "A", "O")
    t["mtf"] = "5m" + t.rel_5m + "_15m" + t.rel_15m + "_1h" + t.rel_1h
    t["n_aligned"] = (t[[f"rel_{h}" for h in TFS]] == "A").sum(axis=1)
    # --- HTF current-regime geometry. P0 = executable entry; extremes = tracker state as of the
    #     last completed 1m bar (causal). Oriented in the HTF regime's OWN direction.
    for h in TFS:
        d = t[f"dir_{h}"]
        fa = t[f"frozen_atr_{h}"]
        hh, ll, sp = t[f"highest_high_{h}"], t[f"lowest_low_{h}"], t[f"start_price_{h}"]
        fav_ext = np.where(d > 0, hh, ll)
        adv_ext = np.where(d > 0, ll, hh)
        rng = (hh - ll)
        t[f"{h}_age_min"] = t[f"age_s_{h}"] / 60.0
        t[f"{h}_bars"] = t[f"bars_{h}"]
        t[f"{h}_mfe_A{h}"] = t[f"mfe_atr_{h}"]
        t[f"{h}_mae_A{h}"] = t[f"mae_atr_{h}"]
        t[f"{h}_retained"] = t[f"retained_{h}"]
        t[f"{h}_range_A{h}"] = rng / fa
        t[f"{h}_disp_A{h}"] = d * (t.P0 - sp) / fa
        t[f"{h}_to_fav_ext_A{h}"] = d * (fav_ext - t.P0) / fa          # >=0 ~ giveback from HTF extreme
        t[f"{h}_to_adv_ext_A{h}"] = d * (t.P0 - adv_ext) / fa
        t[f"{h}_to_fav_ext_A1m"] = d * (fav_ext - t.P0) / t.A
        t[f"{h}_to_start_A1m"] = d * (t.P0 - sp) / t.A
        t[f"{h}_loc_in_range"] = np.where(rng > 0, d * (t.P0 - adv_ext) / rng.where(rng > 0), np.nan)
        t[f"{h}_atr_ratio_to_1m"] = fa / t.A
        t[f"{h}_atr_now_vs_frozen"] = t[f"atr_{h}"] / fa
    return t, excluded, lad


# ----------------------------------------------------------------------------------------------
# statistics helpers
# ----------------------------------------------------------------------------------------------
def clustered_se(x: pd.Series, g: pd.Series) -> float:
    x = x.astype(float)
    n = len(x)
    if n < 2:
        return np.nan
    r = (x - x.mean()).groupby(g.values).sum()
    G = len(r)
    if G < 2:
        return np.nan
    return float(np.sqrt(G / (G - 1) * (r ** 2).sum()) / n)


def top_share(p: pd.Series, q: float) -> dict:
    """Sum of the best q-fraction of trades in A, and the mean of everything else. A 'share of
    total' is not reported because the 2023 total is negative (a share would flip sign)."""
    k = max(1, int(round(len(p) * q)))
    v = np.sort(p.values)[::-1]
    return {"n_top": k, "sum_top_A": float(v[:k].sum()), "sum_rest_A": float(v[k:].sum()),
            "mean_rest_A": float(v[k:].mean()), "total_A": float(v.sum())}


def summ(df: pd.DataFrame, total_n: int | None = None) -> dict:
    n = len(df)
    r = {"n": n}
    if total_n:
        r["share"] = n / total_n
    if n < MIN_N:
        r["below_min_n"] = True
        return r
    p = df.pnl
    r.update({
        "mean_pnl_A": p.mean(), "se_day_clustered": clustered_se(p, df.day), "median_pnl_A": p.median(),
        "p05": p.quantile(.05), "p25": p.quantile(.25), "p75": p.quantile(.75), "p95": p.quantile(.95),
        "p99": p.quantile(.99),
        "win_rate": (p > FLAT).mean(), "loss_rate": (p < -FLAT).mean(), "flat_rate": (p.abs() <= FLAT).mean(),
        "median_dur_s": df.dur.median(), "p90_dur_s": df.dur.quantile(.9),
        "early_fail_rate": early_fail(df).mean(), "runner3_rate": (df.mfe_rung >= 3).mean(),
        "sum_pnl_A": p.sum(), "sum_pnl_ex_top1pct_A": p.sum() - np.sort(p.values)[::-1][:max(1, n // 100)].sum(),
    })
    for x in [0.5, 1.0, 2.0, 3.0, 5.0]:
        r[f"p_fav_{tag(x)}"] = np.isfinite(df[f"tf_{tag(x)}"]).mean()
    for x in [0.5, 1.0, 2.0]:
        r[f"p_adv_{tag(x)}"] = np.isfinite(df[f"ta_{tag(x)}"]).mean()
    return r


def early_fail(df):
    # EARLY FAILURE (declared once, used everywhere): -0.50A reached within 60 s of E and before +0.50A
    return (df.ta_0p50 <= 60) & (df.ta_0p50 < df.tf_0p50)


def auc(score: pd.Series, y: pd.Series) -> float:
    ok = score.notna() & y.notna()
    s, yy = score[ok].values, y[ok].values.astype(bool)
    n1, n0 = yy.sum(), (~yy).sum()
    if n1 < 30 or n0 < 30:
        return np.nan
    r = rankdata(s)
    return float((r[yy].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def qbuckets(s: pd.Series, q=5):
    edges = np.unique(np.nanquantile(s.dropna(), np.linspace(0, 1, q + 1)))
    if len(edges) < 3:
        return None, None
    b = pd.cut(s, edges, include_lowest=True, duplicates="drop")
    return b, edges.tolist()


# ----------------------------------------------------------------------------------------------
# sections
# ----------------------------------------------------------------------------------------------
def s1_population(t, excluded, ident, lad_all):
    N = len(t)
    p = t.pnl
    pop = {
        "frame": ident,
        "trades_t0_total": N + len(excluded),
        "trades_resolved_terminal": N,
        "excluded_unresolved_terminal": {"n": len(excluded),
                                         "reasons": excluded.fillna("<null>").astype(str).value_counts().reset_index().to_dict("records")},
        "coordinates": {
            "A": "atr_entry_1m -- 1m Wilder ATR frozen at the confirmed flip (outcome contract ATR)",
            "E": "executable entry = next 1s open after the T0 checkpoint; T0 = flip-bar close + 15 s",
            "entry_delay_from_flip_close_s": 15,
            "pnl": "terminal_gross_pnl_atr: exit = open of first bar after the opposite flip; gross, no costs",
        },
        "A_points_quantiles": t.A.quantile([.05, .25, .5, .75, .95]).to_dict(),
        "long_short": t.side.value_counts().to_dict(),
        "pnl_A": {"mean": p.mean(), "se_day_clustered": clustered_se(p, t.day), "median": p.median(),
                  "std": p.std(), "quantiles": p.quantile([.001, .01, .05, .1, .25, .5, .75, .9, .95, .99, .999]).to_dict(),
                  "sum": p.sum(), "min": p.min(), "max": p.max()},
        "pnl_A_by_side": {s: {"n": len(g), "mean": g.pnl.mean(), "median": g.pnl.median(),
                              "se_day_clustered": clustered_se(g.pnl, g.day)} for s, g in t.groupby("side")},
        "outcome_bands": {"win_gt_+0.25A": (p > FLAT).mean(), "loss_lt_-0.25A": (p < -FLAT).mean(),
                          "flat_within_0.25A": (p.abs() <= FLAT).mean(), "positive": (p > 0).mean()},
        "duration_s": t.dur.quantile([.01, .05, .1, .25, .5, .75, .9, .95, .99, 1.0]).to_dict(),
        "duration_after_1515_ct_share": float((pd.to_datetime(t.terminal_exit_ts, utc=True).dt.tz_convert("America/Chicago").dt.hour * 60
                                               + pd.to_datetime(t.terminal_exit_ts, utc=True).dt.tz_convert("America/Chicago").dt.minute > 15 * 60 + 15).mean()),
        "entry_extension_A_quantiles": t.entry_ext_A.quantile([.05, .25, .5, .75, .95]).to_dict(),
        "tail_share_of_gross": {f"top_{q*100:g}pct": top_share(p, q) for q in [.10, .05, .02, .01, .005]},
        "gross_ex_top_q": {f"ex_top_{q*100:g}pct_mean_A": float(np.sort(p.values)[::-1][max(1, int(round(N*q))):].mean())
                           for q in [.01, .02, .05]},
        "by_month": t.groupby("month").pnl.agg(["size", "mean", "median"]).reset_index().to_dict("records"),
    }
    jdump("phase_c_2023_population_summary.json", pop)
    return pop


def s1_milestones(t):
    N = len(t)
    rows = []
    for side, levels in [("tf", FAV), ("ta", ADV)]:
        for x in levels:
            tt = t[f"{side}_{tag(x)}"]
            hit = np.isfinite(tt)
            r = {"milestone": ("+" if side == "tf" else "-") + f"{x:.2f}A", "n": N, "p_hit_in_lifecycle": hit.mean(),
                 "n_hit": int(hit.sum()),
                 "time_s_quantiles_given_hit": tt[hit].quantile([.1, .25, .5, .75, .9]).to_dict() if hit.sum() else {},
                 "cum_incidence_by_s": {str(s): float((tt <= s).mean()) for s in INC_S},
                 "p_hit_after_lifecycle_only": None}
            rows.append(r)
    # ladder continuation: P(reach next rung | reached this rung)  (memoryless => continuum, not clusters)
    cont = []
    for side, levels in [("tf", FAV), ("ta", ADV)]:
        for a, b in zip(levels[:-1], levels[1:]):
            ha = np.isfinite(t[f"{side}_{tag(a)}"])
            hb = np.isfinite(t[f"{side}_{tag(b)}"])
            cont.append({"side": "fav" if side == "tf" else "adv", "from": a, "to": b, "n_from": int(ha.sum()),
                         "p_continue": float(hb[ha].mean()) if ha.sum() else None,
                         "p_continue_per_A": float(hb[ha].mean() ** (1 / (b - a))) if ha.sum() and hb[ha].mean() > 0 else None})
    # races: P(+X before -Y), P(-Y before +X), P(neither in lifecycle), ties
    races = []
    for x in [0.25, 0.5, 1.0, 2.0, 3.0]:
        for y in [0.25, 0.5, 1.0, 2.0]:
            f, a = t[f"tf_{tag(x)}"], t[f"ta_{tag(y)}"]
            races.append({"fav": x, "adv": y, "p_fav_first": float((f < a).mean()), "p_adv_first": float((a < f).mean()),
                          "p_tie_same_second": float(((f == a) & np.isfinite(f)).mean()),
                          "p_neither": float((~np.isfinite(f) & ~np.isfinite(a)).mean())})
    # MFE before first -Y  /  MAE before first +X   (ladder-interval: value is the highest rung reached strictly before)
    before = []
    for y in [0.25, 0.5, 1.0]:
        a = t[f"ta_{tag(y)}"]
        hitA = np.isfinite(a)
        r = pd.Series(0.0, index=t.index)
        for x in FAV:
            r = r.where(~(t[f"tf_{tag(x)}"] < a), x)
        dist = r[hitA].value_counts(normalize=True).sort_index()
        before.append({"quantity": f"MFE_before_first_-{y:.2f}A", "n_reaching_adverse": int(hitA.sum()),
                       "share_never_reaching_adverse_in_lifecycle": float((~hitA).mean()),
                       "rung_lower_bound_distribution": {f"{k:.2f}": float(v) for k, v in dist.items()},
                       "median_rung_lower_bound": float(r[hitA].median()) if hitA.sum() else None})
    for x in [0.5, 1.0, 2.0]:
        f = t[f"tf_{tag(x)}"]
        hitF = np.isfinite(f)
        r = pd.Series(0.0, index=t.index)
        for y in ADV:
            r = r.where(~(t[f"ta_{tag(y)}"] < f), y)
        dist = r[hitF].value_counts(normalize=True).sort_index()
        before.append({"quantity": f"MAE_before_first_+{x:.2f}A", "n_reaching_favorable": int(hitF.sum()),
                       "share_never_reaching_favorable_in_lifecycle": float((~hitF).mean()),
                       "rung_lower_bound_distribution": {f"{k:.2f}": float(v) for k, v in dist.items()},
                       "median_rung_lower_bound": float(r[hitF].median()) if hitF.sum() else None})
    # joint lifecycle MFE-rung x MAE-rung
    joint = pd.crosstab(t.mfe_rung, t.mae_rung)
    jpnl = t.pivot_table(index="mfe_rung", columns="mae_rung", values="pnl", aggfunc="mean")
    out = {"n": N, "rule": "in-lifecycle = first passage (s from E) <= time from E to the opposite flip; ladder values are LOWER BOUNDS (interval to next rung)",
           "milestones": rows, "ladder_continuation": cont, "races": races, "excursion_before": before,
           "joint_mfe_mae_rung_counts": {f"mfe>={i:.2f}": {f"mae>={j:.2f}": int(v) for j, v in r.items()} for i, r in joint.iterrows()},
           "joint_mfe_mae_rung_mean_pnl": {f"mfe>={i:.2f}": {f"mae>={j:.2f}": (None if pd.isna(v) else float(v)) for j, v in r.items()} for i, r in jpnl.iterrows()},
           "mfe_rung_distribution": t.mfe_rung.value_counts(normalize=True).sort_index().to_dict(),
           "exit_mechanism_non_runners": exit_mechanism(t),
           "mae_rung_distribution": t.mae_rung.value_counts(normalize=True).sort_index().to_dict()}
    jdump("phase_c_2023_milestone_atlas.json", out)
    return out


def s2_mtf(t):
    N = len(t)
    rows = []
    for cfg, g in t.groupby("mtf"):
        r = {"config": cfg, "side": "POOLED", **summ(g, N)}
        rows.append(r)
        for s, gs in g.groupby("side"):
            rows.append({"config": cfg, "side": s, **summ(gs, N)})
    for k, g in t.groupby("n_aligned"):
        rows.append({"config": f"n_htf_aligned={k}", "side": "POOLED", **summ(g, N)})
    raw = []
    for cfg, g in t.groupby(["side", "dir_5m", "dir_15m", "dir_1h"]):
        raw.append({"side": cfg[0], "dir_5m": cfg[1], "dir_15m": cfg[2], "dir_1h": cfg[3], **summ(g, N)})
    out = {"n": N, "config_code": "5m/15m/1h each A=aligned with the new 1m direction, O=opposed", "rows": rows,
           "raw_direction_rows": raw}
    pd.DataFrame(rows).to_parquet(OUT / "phase_c_2023_mtf_direction_atlas.parquet", index=False)
    jdump("phase_c_2023_mtf_direction_atlas.json", out)
    return out


MATURITY_VARS = ["age_min", "mfe_A{h}", "mae_A{h}", "retained", "disp_A{h}", "range_A{h}", "atr_ratio_to_1m"]
GEOM_VARS = ["to_fav_ext_A{h}", "to_adv_ext_A{h}", "loc_in_range", "to_fav_ext_A1m", "to_start_A1m"]


def bucket_table(t, col, strata="rel"):
    b, edges = qbuckets(t[col])
    if b is None:
        return None
    rows = []
    for h in [None]:
        pass
    for key, g in t.groupby(b, observed=True):
        rows.append({"bucket": str(key), "rel": "ALL", **summ(g, len(t))})
    return {"var": col, "edges_2023": edges, "rows": rows}


def s3_s4(t):
    N = len(t)
    out3, out4 = {"n": N, "per_tf": {}}, {"n": N, "per_tf": {}}
    edges = {}
    for h in TFS:
        for dest, vars_ in [(out3, MATURITY_VARS), (out4, GEOM_VARS)]:
            tab = []
            for v in vars_:
                col = f"{h}_" + v.format(h=h)
                for rel, g in t.groupby(f"rel_{h}"):
                    b, e = qbuckets(g[col])
                    if b is None:
                        continue
                    edges[f"{col}|rel_{h}={rel}"] = e
                    for key, gb in g.groupby(b, observed=True):
                        tab.append({"var": col, "rel_to_1m": rel, "bucket": str(key), **summ(gb, N)})
                    tab.append({"var": col, "rel_to_1m": rel, "bucket": "SPEARMAN_vs_pnl",
                                "n": int(g[col].notna().sum()),
                                "rho": float(spearmanr(g[col], g.pnl, nan_policy="omit")[0])})
            dest["per_tf"][h] = tab
    # named contrast (section 4): same-direction 1m flip at the extreme of a mature 1h move vs near the 1h start
    a = t[t.rel_1h == "A"]
    q_mfe = a["1h_mfe_A1h"].quantile([1 / 3, 2 / 3]).tolist()
    q_loc = a["1h_loc_in_range"].quantile([1 / 3, 2 / 3]).tolist()
    mature = a["1h_mfe_A1h"] >= q_mfe[1]
    young = a["1h_mfe_A1h"] <= q_mfe[0]
    near_ext = a["1h_loc_in_range"] >= q_loc[1]
    near_start = a["1h_loc_in_range"] <= q_loc[0]
    contrast = {"definition": "1h aligned with 1m; 1h MFE (A1h) and 1h location-in-range terciles are 2023 quantiles among 1h-aligned trades",
                "tercile_edges_1h_mfe_A1h": q_mfe, "tercile_edges_1h_loc_in_range": q_loc,
                "mature_1h_at_extreme": summ(a[mature & near_ext], N),
                "mature_1h_deep_retrace_near_start": summ(a[mature & near_start], N),
                "young_1h_at_extreme": summ(a[young & near_ext], N),
                "young_1h_near_start": summ(a[young & near_start], N)}
    out4["named_contrast_1h"] = contrast
    for h in TFS:
        out4.setdefault("causality_note", "P0 = executable entry (1s); HTF start/HH/LL = regime.excursion state as of the last completed 1m bar; "
                        "start_price = open of the HTF flip bar; frozen ATR = HTF Wilder ATR frozen at the HTF flip")
    out3["edges"] = {k: v for k, v in edges.items() if any(x in k for x in ["age_min", "mfe_A", "mae_A", "retained", "disp_A", "range_A", "atr_ratio"])}
    out4["edges"] = {k: v for k, v in edges.items() if k not in out3["edges"]}
    jdump("phase_c_2023_htf_geometry_atlas.json", {"maturity_section3": out3, "geometry_section4": out4})
    pd.DataFrame([dict(r, tf=h, section=3) for h in TFS for r in out3["per_tf"][h]] +
                 [dict(r, tf=h, section=4) for h in TFS for r in out4["per_tf"][h]]).to_parquet(
        OUT / "phase_c_2023_htf_geometry_atlas.parquet", index=False)
    return out3, out4


PRIOR_COLS = [f"prior_{tf}_regime_{v}" for tf in ["1m", "5m"] for v in
              ["efficiency", "mfe_atr", "duration_min", "net_directional_move_atr", "range_atr"]]


def s5_prior(t):
    N = len(t)
    tab = []
    for col in PRIOR_COLS:
        b, e = qbuckets(t[col])
        if b is None:
            continue
        for key, g in t.groupby(b, observed=True):
            tab.append({"var": col, "bucket": str(key), **summ(g, N)})
        tab.append({"var": col, "bucket": "SPEARMAN_vs_pnl", "n": int(t[col].notna().sum()),
                    "rho": float(spearmanr(t[col], t.pnl, nan_policy="omit")[0]), "edges_2023": e})
    out = {"n": N, "available": PRIOR_COLS,
           "NOT_RECOVERABLE": {
               "prior_15m_and_1h_regime_anything": "no prior-context instance exists at 15m/1h (feature family is limited to 5s/1m/5m, gap G3) and the regime.excursion tracker carries only the CURRENT regime",
               "prior_regime_price_levels_any_tf": "prior regime start/MFE-extreme/MAE-extreme PRICES are not carried for any timeframe (only ATR-normalised shape in the prior regime's own ATR), so the ATR distance from T0 to an inherited prior-regime level cannot be computed without re-reading bars -- which would be a bespoke collector",
               "platform_gap": "PRIOR_REGIME_LEVEL_SNAPSHOT: a tracker-state (not feature-family) snapshot of the prior regime's start_price / extreme prices / frozen_atr per timeframe, exposed as metadata like the current-regime excursion state"},
           "rows": tab}
    jdump("phase_c_2023_prior_regime_geometry.json", out)
    return out


def s6_hier(t):
    N = len(t)
    rows = []
    named = {
        "1h+15m aligned, 5m opposed": (t.rel_1h == "A") & (t.rel_15m == "A") & (t.rel_5m == "O"),
        "1h aligned, 15m+5m opposed": (t.rel_1h == "A") & (t.rel_15m == "O") & (t.rel_5m == "O"),
        "all HTF aligned": t.n_aligned == 3,
        "all HTF opposed": t.n_aligned == 0,
        "1h opposed, 5m+15m aligned": (t.rel_1h == "O") & (t.rel_15m == "A") & (t.rel_5m == "A"),
    }
    for name, msk in named.items():
        g = t[msk]
        rows.append({"level": 0, "cell": name, **summ(g, N)})
        # -> 1h maturity (2023 terciles of 1h MFE within the cell)
        for v in ["1h_mfe_A1h", "1h_loc_in_range", "5m_to_fav_ext_A5m"]:
            q = g[v].quantile([1 / 3, 2 / 3]).tolist()
            lab = pd.cut(g[v], [-np.inf, q[0], q[1], np.inf], labels=["T1_low", "T2_mid", "T3_high"])
            for L, gg in g.groupby(lab, observed=True):
                rows.append({"level": 1, "cell": name, "split": v, "tercile": str(L), "edges": q, **summ(gg, N)})
    # hierarchical: config -> 1h MFE tercile -> 1h location tercile (global 2023 terciles), min N
    qm = t["1h_mfe_A1h"].quantile([1 / 3, 2 / 3]).tolist()
    ql = t["1h_loc_in_range"].quantile([1 / 3, 2 / 3]).tolist()
    t = t.assign(m1h=pd.cut(t["1h_mfe_A1h"], [-np.inf, *qm, np.inf], labels=["young", "mid", "mature"]),
                 l1h=pd.cut(t["1h_loc_in_range"], [-np.inf, *ql, np.inf], labels=["near_adv_ext", "middle", "near_fav_ext"]))
    hier = []
    for keys, g in t.groupby(["mtf", "m1h", "l1h"], observed=True):
        if len(g) >= MIN_N_HIER:
            hier.append({"mtf": keys[0], "1h_maturity": keys[1], "1h_location": keys[2], **summ(g, N)})
    out = {"n": N, "named_cells": rows, "hierarchy_min_n": MIN_N_HIER, "hier_edges_1h_mfe": qm,
           "hier_edges_1h_loc": ql, "hierarchy": hier,
           "hier_cells_suppressed": int(t.groupby(["mtf", "m1h", "l1h"], observed=True).size().lt(MIN_N_HIER).sum())}
    jdump("phase_c_2023_cross_tf_geometry.json", out)
    return out


ARCH_ORDER = ["STAGNANT_QUIET", "FAILURE_RAPID", "FAILURE_SLOW", "SHALLOW_FADE", "SHALLOW_RECOVERED",
              "DEVELOPED_GIVEBACK", "DEVELOPED_HELD", "RUNNER_3_5", "RUNNER_5PLUS"]


def classify(t, rapid_edge):
    mfe, pnl = t.mfe_rung, t.pnl
    adv_first = t.ta_0p50 < t.tf_0p50
    reached_m05 = np.isfinite(t.ta_0p50)
    c = pd.Series("UNSET", index=t.index)
    c[(mfe < 0.5) & ~reached_m05] = "STAGNANT_QUIET"
    c[(mfe < 0.5) & reached_m05 & (t.ta_0p50 <= rapid_edge)] = "FAILURE_RAPID"
    c[(mfe < 0.5) & reached_m05 & (t.ta_0p50 > rapid_edge)] = "FAILURE_SLOW"
    c[(mfe >= 0.5) & (mfe < 1.0) & ~adv_first] = "SHALLOW_FADE"
    c[(mfe >= 0.5) & (mfe < 1.0) & adv_first] = "SHALLOW_RECOVERED"
    dev = (mfe >= 1.0) & (mfe < 3.0)
    c[dev & (pnl < 0.5 * mfe)] = "DEVELOPED_GIVEBACK"
    c[dev & (pnl >= 0.5 * mfe)] = "DEVELOPED_HELD"
    c[(mfe >= 3.0) & (mfe < 5.0)] = "RUNNER_3_5"
    c[mfe >= 5.0] = "RUNNER_5PLUS"
    return c, adv_first


ARCH_DEF = {
    "precedence_axis": "lifecycle MFE rung (collected ladder), then first-passage ORDER of +/-0.50A, then time to -0.50A, then capture",
    "STAGNANT_QUIET": "MFE < +0.50A and -0.50A never reached in lifecycle",
    "FAILURE_RAPID": "MFE < +0.50A, -0.50A reached at s <= RAPID_EDGE (2023 median time-to--0.50A within the MFE<0.5 & -0.5 reached group)",
    "FAILURE_SLOW": "MFE < +0.50A, -0.50A reached at s > RAPID_EDGE",
    "SHALLOW_FADE": "+0.50A <= MFE < +1.00A, +0.50A reached before -0.50A (or -0.50A never)",
    "SHALLOW_RECOVERED": "+0.50A <= MFE < +1.00A, -0.50A reached BEFORE +0.50A",
    "DEVELOPED_GIVEBACK": "+1.00A <= MFE < +3.00A and terminal gross < 0.5 x MFE rung (lower bound)",
    "DEVELOPED_HELD": "+1.00A <= MFE < +3.00A and terminal gross >= 0.5 x MFE rung",
    "RUNNER_3_5": "+3.00A <= MFE < +5.00A",
    "RUNNER_5PLUS": "MFE >= +5.00A",
    "flag_ADVERSE_FIRST": "-0.50A reached before +0.50A (orthogonal flag, reported inside every class)",
    "flag_LONG_QUIET": "duration >= 2023 p75 duration and MFE < 1A and MAE < 1A",
    "note": "0.5 capture and the 1/3/5 rungs are structural rungs of the collected ladder, not economics-optimised cutoffs",
}


def s7_archetypes(t):
    N = len(t)
    g0 = t[(t.mfe_rung < 0.5) & np.isfinite(t.ta_0p50)]
    rapid_edge = float(g0.ta_0p50.median())
    p75d = float(t.dur.quantile(.75))
    t["arch"], t["adv_first"] = classify(t, rapid_edge)
    t["long_quiet"] = (t.dur >= p75d) & (t.mfe_rung < 1) & (t.mae_rung < 1)
    assert (t.arch != "UNSET").all()
    rows = []
    for a in ARCH_ORDER:
        g = t[t.arch == a]
        r = {"archetype": a, **summ(g, N)}
        if len(g) >= 30:
            r.update({"sum_pnl_A": g.pnl.sum(), "adverse_first_share": g.adv_first.mean(),
                      "long_quiet_share": g.long_quiet.mean(), "long_share": (g.side == "LONG").mean(),
                      "mtf_all_aligned_share": (g.n_aligned == 3).mean(), "mtf_all_opposed_share": (g.n_aligned == 0).mean(),
                      "median_entry_ext_A": g.entry_ext_A.median(), "median_1h_mfe_A1h": g["1h_mfe_A1h"].median(),
                      "median_1h_loc": g["1h_loc_in_range"].median(), "median_5m_to_fav_ext_A5m": g["5m_to_fav_ext_A5m"].median(),
                      "median_s_to_first_0p25_fav": g.tf_0p25.replace(np.inf, np.nan).median(),
                      "median_s_to_first_0p25_adv": g.ta_0p25.replace(np.inf, np.nan).median(),
                      "share_first_move_adverse_0p25": (g.ta_0p25 < g.tf_0p25).mean(),
                      "mae_rung_dist": g.mae_rung.value_counts(normalize=True).sort_index().to_dict(),
                      "mtf_config_share": g.mtf.value_counts(normalize=True).to_dict()})
        rows.append(r)
    # separability of T0 state across archetypes: max |AUC-0.5| of T0 features one-vs-rest
    feats = t0_feature_list(t)
    sep = []
    for a in ARCH_ORDER:
        y = t.arch == a
        if y.sum() < 100:
            continue
        best = sorted(((abs(auc(t[f], y) - .5), f, auc(t[f], y)) for f in feats if t[f].notna().sum() > 1000),
                      key=lambda z: -np.nan_to_num(z[0]))[:5]
        sep.append({"archetype": a, "n": int(y.sum()), "top_t0_features": [{"feature": f, "auc": v} for _, f, v in best]})
    # bimodality check on time to -0.50A and duration (log-scale histogram)
    ta = t.ta_0p50[np.isfinite(t.ta_0p50)]
    hist_ta = np.histogram(np.log10(ta.clip(lower=1)), bins=20)
    hist_d = np.histogram(np.log10(t.dur), bins=20)
    out = {"n": N, "definitions": ARCH_DEF, "RAPID_EDGE_s": rapid_edge, "LONG_QUIET_duration_p75_s": p75d, "rows": rows,
           "t0_separability": sep,
           "shape_diagnostics": {"log10_time_to_-0.50A_hist": {"counts": hist_ta[0].tolist(), "edges": hist_ta[1].tolist()},
                                 "log10_duration_hist": {"counts": hist_d[0].tolist(), "edges": hist_d[1].tolist()}}}
    jdump("phase_c_2023_path_archetypes.json", out)
    t[["regime_start_ns", "arch", "adv_first", "long_quiet", "mfe_rung", "mae_rung", "pnl", "dur"]].to_parquet(
        OUT / "phase_c_2023_path_archetypes.parquet", index=False)
    return out


def t0_feature_list(t):
    fam = feature_families(t)
    return [f for fs in fam.values() for f in fs]


def feature_families(t):
    fam = {
        "1m_state_path": ["entry_ext_A", "flipbar_mfe_A", "flipbar_mae_A", "retained_1m", "progress_windows_1m",
                          "atr_ratio_1m_now_vs_frozen"],
        "volatility_range": ["A_points", "1h_atr_now_vs_frozen", "15m_atr_now_vs_frozen", "5m_atr_now_vs_frozen"],
        "pullback_velocity": ["rolling_60s_giveback_atr", "rolling_300s_giveback_atr"],
        "cross_tf_alignment": ["n_aligned", "regime_alignment", "rel5m_num", "rel15m_num", "rel1h_num"],
        "prior_1m_geometry": [c for c in PRIOR_COLS if "_1m_" in c],
        "prior_5m_geometry": [c for c in PRIOR_COLS if "_5m_" in c],
        "context_time": ["ct_hour"],
        "5m_geometry_features": ["current_5m_regime_mfe_atr", "current_5m_regime_efficiency", "current_5m_regime_range_atr",
                                 "distance_to_completed_5m_high_atr", "distance_to_completed_5m_low_atr",
                                 "current_5m_regime_age_min"],
    }
    for h in TFS:
        fam[f"{h}_maturity"] = [f"{h}_" + v.format(h=h) for v in MATURITY_VARS]
        fam[f"{h}_current_geometry"] = [f"{h}_" + v.format(h=h) for v in GEOM_VARS]
    for h in TFS:
        t[f"rel{h}_num"] = (t[f"rel_{h}"] == "A").astype(float)
    return {k: [f for f in v if f in t.columns] for k, v in fam.items()}


# ---- section 8: state transitions -------------------------------------------------------------
def build_panel(m, t):
    """Checkpoint rows of resolved trades while the trade is still alive, with T0-anchored state."""
    p = m[m.regime_start_ns.isin(t.regime_start_ns)].copy()
    base = t.set_index("regime_start_ns")
    for c in ["P0", "A", "terminal_flip_ts", "pnl", "mfe_rung", "mae_rung", "arch", "day"] + \
             [f"tf_{tag(x)}" for x in FAV] + [f"ta_{tag(x)}" for x in ADV]:
        p["T0_" + c] = p.regime_start_ns.map(base[c])
    p = p[p.observation_ts < p.T0_terminal_flip_ts].copy()     # same-instant rows at/after the flip excluded
    p["s"] = p.checkpoint_index * 15
    p["cur_pnl_A"] = p.dir_1m * (p.last_close_1m - p.T0_P0) / p.T0_A
    p["rem_pnl_A"] = p.terminal_gross_pnl_atr                  # this row's own entry -> same flip
    p["mfe_by_s"] = 0.0
    p["mae_by_s"] = 0.0
    for x in FAV:
        p["mfe_by_s"] = p.mfe_by_s.where(~(p[f"T0_tf_{tag(x)}"] <= p.s), x)
    for x in ADV:
        p["mae_by_s"] = p.mae_by_s.where(~(p[f"T0_ta_{tag(x)}"] <= p.s), x)
    p["hh_new_since_T0"] = np.nan
    return p


def fut(g, x, side="tf"):
    """P(T0-anchored rung reached in lifecycle AFTER s | not reached by s)."""
    col = g[f"T0_{side}_{tag(x)}"]
    notyet = col > g.s
    return float((np.isfinite(col) & notyet).sum() / notyet.sum()) if notyet.sum() >= 30 else None


def s8_transitions(m, t):
    p = build_panel(m, t)
    alive = p.groupby("s").size().to_dict()
    grid = []
    for s in CHECK_S:
        g = p[p.s == s]
        for (a, b), gg in g.groupby([g.mfe_by_s.clip(upper=2.0), g.mae_by_s.clip(upper=1.0)]):
            r = {"s": s, "mfe_rung_by_s": a, "mae_rung_by_s": b, "n": len(gg), "share_of_alive": len(gg) / len(g)}
            if len(gg) >= MIN_N:
                r.update({"mean_rem_pnl_A": gg.rem_pnl_A.mean(), "se": clustered_se(gg.rem_pnl_A, gg.T0_day),
                          "median_rem_pnl_A": gg.rem_pnl_A.median(), "mean_total_pnl_A": gg.T0_pnl.mean(),
                          "p_future_fav_2p00": fut(gg, 2.0), "p_future_fav_3p00": fut(gg, 3.0), "p_future_fav_5p00": fut(gg, 5.0),
                          "p_future_adv_1p00": fut(gg, 1.0, "ta"), "p_future_adv_2p00": fut(gg, 2.0, "ta"),
                          "median_remaining_life_s": float((gg.T0_terminal_flip_ts - gg.observation_ts).median() / 1e9)})
            grid.append(r)
    scen = {}
    # a) -0.25A within 30 s
    first = p[p.s == 30]
    c = first[first.T0_ta_0p25 <= 30]
    scen["adv_0p25_within_30s"] = scen_summary(c, first)
    c = first[first.T0_tf_0p25 <= 30]
    scen["fav_0p25_within_30s(reference)"] = scen_summary(c, first)
    # b) +0.75A MFE but back near entry
    for s in [60, 120, 180, 285]:
        g = p[p.s == s]
        c = g[(g.mfe_by_s >= 0.75) & (g.cur_pnl_A.abs() <= FLAT)]
        scen[f"mfe_0p75_back_near_entry_at_{s}s"] = scen_summary(c, g)
    # c) +1A rapidly
    for lim in [30, 60, 120]:
        g = p[p.s == min(lim, 285)]
        c = g[g.T0_tf_1p00 <= lim]
        scen[f"fav_1p00_within_{lim}s"] = scen_summary(c, g, extra=True)
    # d) little progress after 120 s
    g = p[p.s == 120]
    c = g[(g.mfe_by_s < 0.5) & (g.mae_by_s < 0.5)]
    scen["little_progress_at_120s(mfe<0.5 & mae<0.5)"] = scen_summary(c, g)
    c = g[(g.mfe_by_s < 0.5) & (g.mae_by_s < 0.5) & (g.cur_pnl_A.abs() <= FLAT)]
    scen["little_progress_and_flat_at_120s"] = scen_summary(c, g)
    # current-pnl conditional (the 'where is price now' view) at each checkpoint, 2023 quintiles of cur_pnl
    curq = []
    for s in CHECK_S:
        g = p[p.s == s]
        b, e = qbuckets(g.cur_pnl_A)
        for key, gg in g.groupby(b, observed=True):
            curq.append({"s": s, "cur_pnl_bucket": str(key), "edges": e, "n": len(gg),
                         "mean_rem_pnl_A": gg.rem_pnl_A.mean(), "se": clustered_se(gg.rem_pnl_A, gg.T0_day),
                         "p_future_fav_3p00": fut(gg, 3.0), "p_future_adv_1p00": fut(gg, 1.0, "ta")})
    out = {"n_trades": len(t), "alive_by_s": alive, "martingale_check": martingale(p, grid),
           "rules": {"alive": "checkpoint observation_ts < the trade's own T0 terminal flip (same-instant rows excluded)",
                     "state": "mfe/mae_rung_by_s = highest T0-anchored ladder rung whose first passage <= s; cur_pnl_A = (last 1s close - E)/A",
                     "remaining": "rem_pnl_A = that checkpoint row's own executable entry -> the same opposite flip (gross, A)",
                     "future_rung": "P(T0-anchored rung reached later in the lifecycle | not yet reached by s)"},
           "grid": grid, "scenarios": scen, "by_current_pnl_quintile": curq}
    jdump("phase_c_2023_state_transitions.json", out)
    pd.DataFrame(grid).to_parquet(OUT / "phase_c_2023_state_transitions.parquet", index=False)
    return out, p


def exit_mechanism(t):
    """For trades that never reach +2A, the terminal sits at the adverse extreme the flip needs."""
    g = t[t.mfe_rung < 2.0]
    return {"n": len(g), "spearman_pnl_vs_neg_mae_rung": float(spearmanr(g.pnl, -g.mae_rung)[0]),
            "mean_pnl_plus_mae_rung_A": float((g.pnl + g.mae_rung).mean()),
            "share_terminal_negative": float((g.pnl < 0).mean())}


def martingale(p, grid):
    out = {}
    for s in [30, 60, 120, 285]:
        g = p[p.s == s]
        out[str(s)] = {"n": len(g), "spearman_cur_pnl_vs_rem_pnl": float(spearmanr(g.cur_pnl_A, g.rem_pnl_A, nan_policy="omit")[0]),
                       "mean_rem_pnl_A": float(g.rem_pnl_A.mean()), "se": clustered_se(g.rem_pnl_A.dropna(), g.T0_day[g.rem_pnl_A.notna()])}
    cells = [r for r in grid if r.get("se") and r["n"] >= MIN_N and r["s"] in (30, 60, 120, 285)]
    z = [abs(r["mean_rem_pnl_A"] / r["se"]) for r in cells if r["se"] > 0]
    out["grid_cells_n_ge_min"] = len(z)
    out["share_cells_abs_z_gt_2"] = float(np.mean([v > 2 for v in z])) if z else None
    return out


def scen_summary(c, g, extra=False):
    r = {"n": len(c), "share_of_alive": len(c) / max(1, len(g)), "s": int(g.s.iloc[0]) if len(g) else None}
    if len(c) < 30:
        return r
    r.update({"mean_rem_pnl_A": c.rem_pnl_A.mean(), "se": clustered_se(c.rem_pnl_A, c.T0_day),
              "mean_rem_pnl_A_alive_reference": g.rem_pnl_A.mean(), "mean_total_pnl_A": c.T0_pnl.mean(),
              "p_future_fav_1p00": fut(c, 1.0), "p_future_fav_2p00": fut(c, 2.0), "p_future_fav_3p00": fut(c, 3.0),
              "p_future_fav_5p00": fut(c, 5.0), "p_future_adv_1p00": fut(c, 1.0, "ta"),
              "p_reach_fav_2p00_total": float(np.isfinite(c.T0_tf_2p00).mean()),
              "p_reach_fav_3p00_total": float(np.isfinite(c.T0_tf_3p00).mean()),
              "archetype_mix": c.T0_arch.value_counts(normalize=True).to_dict()})
    if extra:
        r["p_giveback_to_le_0_terminal"] = float((c.T0_pnl <= 0).mean())
        r["p_terminal_lt_half_mfe"] = float((c.T0_pnl < 0.5 * c.T0_mfe_rung).mean())
    return r


def s9_runners(t):
    N, tot = len(t), t.pnl.sum()
    rows = []
    for x in [1.0, 2.0, 3.0, 4.0, 5.0]:
        g = t[t.mfe_rung >= x]
        tt = g[f"tf_{tag(x)}"]
        mae_before = pd.Series(0.0, index=g.index)
        for y in ADV:
            mae_before = mae_before.where(~(g[f"ta_{tag(y)}"] < tt), y)
        rows.append({"population": f"MFE>=+{x:.0f}A", "n": len(g), "freq": len(g) / N,
                     "sum_pnl_A": g.pnl.sum(),
                     "mean_pnl_A": g.pnl.mean(), "median_pnl_A": g.pnl.median(),
                     "capture_median_pnl_over_rung": float((g.pnl / x).median()),
                     "p_terminal_le_0": float((g.pnl <= 0).mean()),
                     "time_to_rung_s": tt.quantile([.1, .25, .5, .75, .9]).to_dict(),
                     "mae_rung_before_rung_dist": mae_before.value_counts(normalize=True).sort_index().to_dict(),
                     "p_adverse_0p50_first": float((g.ta_0p50 < g.tf_0p50).mean()),
                     "mtf_config_share": g.mtf.value_counts(normalize=True).to_dict(),
                     "n_aligned_dist": g.n_aligned.value_counts(normalize=True).sort_index().to_dict(),
                     "median_entry_ext_A": g.entry_ext_A.median(),
                     "median_1h_mfe_A1h": g["1h_mfe_A1h"].median(), "median_1h_loc": g["1h_loc_in_range"].median(),
                     "median_15m_loc": g["15m_loc_in_range"].median(), "median_5m_loc": g["5m_loc_in_range"].median(),
                     "median_dur_s": g.dur.median(),
                     "long_share": (g.side == "LONG").mean()})
    base = {"population": "ALL", "n": N, "median_entry_ext_A": t.entry_ext_A.median(),
            "median_1h_mfe_A1h": t["1h_mfe_A1h"].median(), "median_1h_loc": t["1h_loc_in_range"].median(),
            "median_15m_loc": t["15m_loc_in_range"].median(), "median_5m_loc": t["5m_loc_in_range"].median(),
            "n_aligned_dist": t.n_aligned.value_counts(normalize=True).sort_index().to_dict(),
            "mtf_config_share": t.mtf.value_counts(normalize=True).to_dict(), "median_dur_s": t.dur.median()}
    contrib = t.groupby("mfe_rung").pnl.agg(["size", "sum", "mean"]).reset_index()
    out = {"n": N, "total_gross_A": tot, "populations": rows, "baseline": base,
           "tail_share_of_gross": {f"top_{q*100:g}pct": top_share(t.pnl, q) for q in [.10, .05, .02, .01, .005]},
           "contribution_by_lifecycle_mfe_rung": contrib.to_dict("records")}
    jdump("phase_c_2023_runner_forensics.json", out)
    return out


def s10_failures(t, p):
    N, tot = len(t), t.pnl.sum()
    rows = []
    for y in [0.5, 1.0, 2.0, 3.0]:
        g = t[t.mae_rung >= y]
        tt = g[f"ta_{tag(y)}"]
        mfe_before = pd.Series(0.0, index=g.index)
        for x in FAV:
            mfe_before = mfe_before.where(~(g[f"tf_{tag(x)}"] < tt), x)
        rows.append({"population": f"MAE>=-{y:.2f}A", "n": len(g), "freq": len(g) / N, "sum_pnl_A": g.pnl.sum(),
                     "mean_pnl_A": g.pnl.mean(), "median_pnl_A": g.pnl.median(),
                     "time_to_adverse_s": tt.quantile([.1, .25, .5, .75, .9]).to_dict(),
                     "mfe_rung_before_adverse_dist": mfe_before.value_counts(normalize=True).sort_index().to_dict(),
                     "p_recover_to_terminal_gt_0": float((g.pnl > 0).mean()),
                     "p_later_fav_2p00": float((np.isfinite(g.tf_2p00) & (g.tf_2p00 > tt)).mean()),
                     "n_aligned_dist": g.n_aligned.value_counts(normalize=True).sort_index().to_dict(),
                     "mtf_config_share": g.mtf.value_counts(normalize=True).to_dict(),
                     "median_entry_ext_A": g.entry_ext_A.median(), "median_1h_mfe_A1h": g["1h_mfe_A1h"].median(),
                     "median_1h_loc": g["1h_loc_in_range"].median(), "median_5m_loc": g["5m_loc_in_range"].median(),
                     "median_dur_s": g.dur.median()})
    # identifiability A/B/C: target = T0-anchored lifecycle reaches -1.00A (and -2.00A)
    feats = t0_feature_list(t)
    ident = []
    for y in [1.0, 2.0]:
        yT = pd.Series(np.isfinite(t[f"ta_{tag(y)}"]).values, index=t.regime_start_ns.values)
        t0 = sorted(((abs(auc(t[f], pd.Series(yT.values, index=t.index)) - .5), f,
                      auc(t[f], pd.Series(yT.values, index=t.index))) for f in feats), key=lambda z: -np.nan_to_num(z[0]))[:5]
        ident.append({"target": f"lifecycle MAE reaches -{y:.2f}A", "stage": "T0", "n": len(t),
                      "base_rate": float(yT.mean()), "top_features": [{"feature": f, "auc": v} for _, f, v in t0]})
        for s in [15, 30, 45, 60, 120]:
            g = p[(p.s == s) & ~(p[f"T0_ta_{tag(y)}"] <= s)]           # still alive and not yet at -y
            yy = np.isfinite(g[f"T0_ta_{tag(y)}"])
            cand = {"cur_pnl_A": g.cur_pnl_A, "mae_by_s": g.mae_by_s, "mfe_by_s": g.mfe_by_s,
                    "rolling_60s_giveback_atr": g.rolling_60s_giveback_atr, "retained_1m": g.retained_1m}
            aucs = {k: auc(v, pd.Series(yy.values, index=g.index)) for k, v in cand.items()}
            # optionality cost of the most adverse path decile at s (descriptive, not a rule)
            q10 = g.cur_pnl_A.quantile(.10)
            worst = g[g.cur_pnl_A <= q10]
            runners = np.isfinite(g.T0_tf_3p00)
            ident.append({"target": f"lifecycle MAE reaches -{y:.2f}A", "stage": f"s={s}", "n_at_risk": len(g),
                          "base_rate_at_risk": float(yy.mean()), "path_auc": aucs,
                          "worst_cur_pnl_decile": {"edge_A": float(q10), "n": len(worst),
                                                   "p_target": float(np.isfinite(worst[f"T0_ta_{tag(y)}"]).mean()),
                                                   "share_of_all_target_events_at_risk": float(np.isfinite(worst[f"T0_ta_{tag(y)}"]).sum() / max(1, yy.sum())),
                                                   "share_of_future_3A_runners_in_decile": float(np.isfinite(worst.T0_tf_3p00).sum() / max(1, runners.sum())),
                                                   "sum_T0_pnl_A_in_decile": float(worst.T0_pnl.sum()),
                                                   "mean_T0_pnl_A": float(worst.T0_pnl.mean())}})
    out = {"n": N, "populations": rows, "identifiability": ident,
           "note": "AUC oriented as P(score higher for target); |AUC-0.5| is the association strength. Path AUCs are among trades still alive and not yet at the target rung at s."}
    jdump("phase_c_2023_failure_forensics.json", out)
    return out


def s11_information(t):
    fam = feature_families(t)
    y = {
        "rapid_failure": t.arch == "FAILURE_RAPID",
        "early_fail_60s": early_fail(t),
        "severe_left_tail_mae_2A": np.isfinite(t.ta_2p00),
        "runner_3A": t.mfe_rung >= 3,
        "giveback_after_1A (MFE>=1A, terminal<=0)": None,
        "stagnation_long_quiet": t.long_quiet,
    }
    rows = []
    dev = t.mfe_rung >= 1
    for fname, feats in fam.items():
        for f in feats:
            x = t[f]
            if x.notna().sum() < 1000 or x.nunique() < 2:
                continue
            r = {"family": fname, "feature": f, "n": int(x.notna().sum()),
                 "spearman_terminal_pnl": float(spearmanr(x, t.pnl, nan_policy="omit")[0])}
            for k, yy in y.items():
                if yy is None:
                    r["auc_" + k] = auc(x[dev], (t.pnl[dev] <= 0))
                else:
                    r["auc_" + k] = auc(x, pd.Series(np.asarray(yy), index=t.index))
            # monotone quintile separation of terminal pnl
            b, _ = qbuckets(x)
            if b is not None:
                mm = t.pnl.groupby(b, observed=True).mean()
                r["quintile_mean_pnl"] = mm.round(4).tolist()
                r["quintile_spread_A"] = float(mm.iloc[-1] - mm.iloc[0])
            rows.append(r)
    df = pd.DataFrame(rows)
    aucc = [c for c in df.columns if c.startswith("auc_")]
    for c in aucc:
        df["abs_" + c] = (df[c] - .5).abs()
    fam_sum = df.groupby("family").agg(
        n_features=("feature", "size"), max_abs_spearman=("spearman_terminal_pnl", lambda s: s.abs().max()),
        **{"max_abs_" + c: ("abs_" + c, "max") for c in aucc}).reset_index()
    # redundancy among the 20 features most associated with any target
    df["assoc"] = df[["abs_" + c for c in aucc]].max(axis=1)
    top = list(dict.fromkeys(df.sort_values("assoc", ascending=False).feature))[:20]
    cm = t[top].rank().corr()
    redund = [{"a": a, "b": b, "spearman": float(cm.loc[a, b])} for i, a in enumerate(top) for b in top[i + 1:]
              if abs(cm.loc[a, b]) >= 0.8]
    df.drop(columns=[c for c in df.columns if c.startswith("abs_")]).to_parquet(OUT / "phase_c_2023_information_map.parquet", index=False)
    out = {"n": len(t), "targets": {k: ("among MFE>=1A: terminal <= 0" if v is None else float(np.asarray(v).mean())) for k, v in y.items()},
           "family_summary": fam_sum.to_dict("records"), "top_features": df.sort_values("assoc", ascending=False).head(25).drop(
               columns=[c for c in df.columns if c.startswith("abs_")]).to_dict("records"),
           "redundant_pairs_abs_rho_ge_0p8": redund}
    jdump("phase_c_2023_information_map.json", out)
    return out


def main():
    m, ident = load_frame(2023)
    t, excluded, lad = build_trades(m)
    res = {"ident": ident}
    res["pop"] = s1_population(t, excluded, ident, lad)
    res["mil"] = s1_milestones(t)
    res["mtf"] = s2_mtf(t)
    res["s3"], res["s4"] = s3_s4(t)
    res["s5"] = s5_prior(t)
    res["s6"] = s6_hier(t)
    res["s7"] = s7_archetypes(t)
    res["s8"], panel = s8_transitions(m, t)
    res["s9"] = s9_runners(t)
    res["s10"] = s10_failures(t, panel)
    res["s11"] = s11_information(t)
    keep = ["regime_start_ns", "day", "side", "A", "P0", "pnl", "dur", "life_s", "mfe_rung", "mae_rung", "mtf", "n_aligned",
            "entry_ext_A", "arch"] + [c for c in t.columns if c.startswith(("tf_", "ta_"))] + \
           [c for c in t.columns if any(c.startswith(h + "_") for h in TFS)]
    t[keep].to_parquet(OUT / "phase_c_2023_trades.parquet", index=False)
    print(json.dumps({"STATUS": "OK", "n_trades": len(t), "excluded": len(excluded), "frame": ident}, default=str))


if __name__ == "__main__":
    main()
