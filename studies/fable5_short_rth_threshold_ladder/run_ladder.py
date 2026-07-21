"""Original-W4 short-RTH threshold-ladder entry-timing diagnostic (offline).

Regenerates the short-RTH first-crossing entry schedule at four prevailing-long
weakness thresholds (0.625, 0.650, 0.675, 0.688350=control) from the frozen
repaired W4 score stream, using the identical established filter and crossing
logic as the original implementation (only the threshold changes), then replays
the confirmed Policy A (1.25 pre stop / 300s timeout / 1.50 post stop / opposing
flip). The control (0.688350) is gated to reproduce the frozen 807-entry
short-RTH schedule exactly. Not retraining, not optimization — a fixed diagnostic.

1-second OHLC research simulation (offline). RTH 08:30-15:00 America/Chicago
(entry only), matching the frozen benchmark. NQ $20/pt, $10 RT, 1 contract.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
STUDY = Path(__file__).resolve().parent
RESULTS, AUDIT, WORK = STUDY / "results", STUDY / "audit", STUDY / "_work"
for d in (RESULTS, AUDIT, WORK):
    d.mkdir(parents=True, exist_ok=True)

for p in (ROOT / "studies" / "fable5_specialized_w4",
          ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair",
          ROOT / "studies" / "regime_sequence_chop_context"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import fable5_common as F  # noqa: E402
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import (  # noqa: E402
    canonical_regime_timeline, is_rth, load_checkpoint_stream,
    progress_window_counts, strict_threshold_cross, validate_raw_bars,
)

NS = 1_000_000_000
MULT, COST = 20.0, 10.0
MAX_AGE_NS = 1800 * NS
THRESHOLDS = [0.625, 0.650, 0.675, 0.6883498713708196]
CONTROL = 0.6883498713708196
POLICY_PATH = (ROOT / "studies" / "CODEX_5_X_weakness_atlas_repair"
               / "CODEX_5_X_established_fade_policy.json")
SCHED_DIR = ROOT / "studies" / "fable5_nt_short_rth_policy_a" / "_work"
MULTI_CAND = ROOT / "studies" / "codex_5_w4_multi_candidate_reentry" / "_work"
ISOLATION = (ROOT / "studies" / "codex_5_w4_fade_confirmation_clock_isolation"
             / "results" / "isolation_trade_diffs.parquet")
POLICY_A_ID = "POLICY_A_COMBINED_1P25_300S"
# Candidate basis = first-crossing short-RTH per prevailing-long regime.
# Executed (fixed-807) basis = the globally one-position-executed subset.
YEAR_CAND_COUNT = {2025: 650, 2026: 222}
YEAR_EXEC_COUNT = {2025: 604, 2026: 203}


def generate_entries(year: int, raw: pd.DataFrame, stream: pd.DataFrame,
                     tau: float, filt: dict) -> pd.DataFrame:
    """First short-fade crossing per prevailing-long regime at threshold tau."""
    ts = raw.index.view(np.int64)
    opens, highs = raw.open.to_numpy(float), raw.high.to_numpy(float)
    rows = []
    for regime_start, group in stream.groupby("regime_start_ns", sort=False):
        group = group.sort_values("observation_time", kind="stable")
        first = group.iloc[0]
        if int(first.direction) != 1:      # prevailing long -> short fade only
            continue
        start_ts, regime_end = int(first.entry_ts_event), int(first.regime_end_ns)
        atr_entry, anchor = float(first.atr_at_entry), float(first.entry_open)
        a = int(np.searchsorted(ts, start_ts, side="left"))
        b = int(np.searchsorted(ts, regime_end, side="left"))
        if a >= b or int(ts[a]) != start_ts:
            raise RuntimeError(f"invalid regime raw path {regime_start}")
        favorable = highs[a:b] - anchor    # long regime favorable = up
        running = np.maximum.accumulate(np.maximum(favorable / atr_entry, 0.0))
        progress = progress_window_counts(running, ts[a:b])
        horizon = int(regime_start) + MAX_AGE_NS
        prev = None
        for cp in group.itertuples(index=False):
            decision = int(cp.observation_time)
            score = float(cp.w4_score)
            crossed = strict_threshold_cross(prev, score, tau)
            prev = score
            k = int(np.searchsorted(ts[a:b], decision, side="left") - 1)
            if k < 0 or decision >= regime_end:
                continue
            if not np.isclose(float(running[k]), float(cp.current_mfe),
                              rtol=0, atol=1e-9):
                raise RuntimeError(f"MFE/raw mismatch {decision}")
            retained = (float(cp.current_pnl) / float(cp.current_mfe)
                        if float(cp.current_mfe) > 0 else np.nan)
            established = bool(
                float(cp.regime_age) >= filt["regime_age_s_min"]
                and float(cp.current_mfe) >= filt["running_mfe_atr_min"]
                and int(progress[k]) >= filt["new_progress_windows_min"]
                and retained >= filt["retained_mfe_ratio_min"])
            if crossed and established and decision <= horizon:
                fill_i = int(np.searchsorted(ts, decision, side="left"))
                if fill_i >= len(ts):
                    break
                fill_ts, fill_px = int(ts[fill_i]), float(opens[fill_i])
                # Guard (matches CODEX_5_X_run_established_fade.simulate): the
                # fill must precede the aligning flip. If a data gap pushes the
                # next open at/after regime_end, there is no valid seq-1 entry
                # for this regime (a later crossing would be later still).
                if fill_ts >= regime_end:
                    break
                rows.append({
                    "year": year, "threshold": tau,
                    "regime_start_ns": int(regime_start),
                    "signal_decision_ts": decision,
                    "entry_fill_ts": fill_ts, "entry_px": fill_px,
                    "atr_at_checkpoint": float(cp.atr_at_checkpoint),
                    "confirm_flip_ns": regime_end, "entry_direction": -1,
                    "w4_score": score,
                    "session": "RTH" if is_rth(fill_ts) else "ETH"})
                break              # seq 1 only
    df = pd.DataFrame(rows)
    if len(df):
        if not (df.entry_fill_ts < df.confirm_flip_ns).all():
            raise RuntimeError(f"{year} tau={tau}: entry fill at/after aligning flip")
        df = df[df.session == "RTH"].reset_index(drop=True)
    return df


def gate_candidate(year: int, ctrl: pd.DataFrame) -> dict:
    """Control candidates must equal the audited multi-candidate seq-1 short-RTH
    population (650/222) — the correct parity target for the regeneration."""
    mc = pd.read_parquet(MULTI_CAND / f"candidates_{year}.parquet")
    mc = mc[(mc.candidate_seq == 1) & (mc.direction == "short_fade")
            & (mc.session == "RTH")].sort_values("candidate_fill_time").reset_index(drop=True)
    mine = ctrl.sort_values("entry_fill_ts").reset_index(drop=True)
    if len(mine) != YEAR_CAND_COUNT[year] or len(mc) != YEAR_CAND_COUNT[year]:
        raise RuntimeError(f"{year} candidate count {len(mine)} != {YEAR_CAND_COUNT[year]}")
    m = 0
    m += int((mine.regime_start_ns.to_numpy(np.int64)
              != mc.regime_start_ns.to_numpy(np.int64)).sum())
    m += int((mine.entry_fill_ts.to_numpy(np.int64)
              != mc.candidate_fill_time.to_numpy(np.int64)).sum())
    m += int((~np.isclose(mine.entry_px, mc.candidate_fill_price, rtol=0, atol=1e-9)).sum())
    m += int((~np.isclose(mine.atr_at_checkpoint, mc.atr_at_checkpoint, rtol=0, atol=1e-12)).sum())
    m += int((mine.confirm_flip_ns.to_numpy(np.int64)
              != mc.confirm_flip_ns.to_numpy(np.int64)).sum())
    if m:
        raise RuntimeError(f"{year} candidate parity mismatch: {m}")
    return {"year": year, "candidate_trades": len(mine), "mismatches": 0}


def gate_fixed807(year: int, fixed_tr: pd.DataFrame) -> dict:
    """Control fixed-807 replay must reproduce the frozen offline Policy A
    short-RTH benchmark (entry, exit reason/px, pnl) trade-for-trade."""
    off = pd.read_parquet(ISOLATION)
    off = off[(off.policy_id == POLICY_A_ID) & (off.year == year)
              & (off.trade_direction == "short_fade") & (off.session == "RTH")]
    off = off.sort_values("entry_fill_ts").reset_index(drop=True)
    mine = fixed_tr.sort_values("entry_fill_ts").reset_index(drop=True)
    if len(mine) != YEAR_EXEC_COUNT[year] or len(off) != YEAR_EXEC_COUNT[year]:
        raise RuntimeError(f"{year} fixed807 count {len(mine)} != {YEAR_EXEC_COUNT[year]}")
    m = int((mine.entry_fill_ts.to_numpy(np.int64) != off.entry_fill_ts.to_numpy(np.int64)).sum())
    m += int((mine.exit_ts.to_numpy(np.int64) != off.new_exit_fill_ts.to_numpy(np.int64)).sum())
    m += int((mine.exit_reason.to_numpy() != off.new_exit_reason.to_numpy()).sum())
    m += int((~np.isclose(mine.net_pnl, off.new_net_pnl_usd, rtol=0, atol=1e-6)).sum())
    if m:
        raise RuntimeError(f"{year} fixed807 control reconciliation mismatch: {m}")
    return {"year": year, "fixed807_trades": len(mine), "mismatches": 0,
            "net_pnl": float(mine.net_pnl.sum())}


def replay(entries: pd.DataFrame, ts, opens, highs, lows, next_ends) -> pd.DataFrame:
    out = []
    for c in entries.itertuples(index=False):
        align_ts = int(c.confirm_flip_ns)
        scheduled = next_ends.get(align_ts)
        if scheduled is None:
            raise RuntimeError(f"missing opposing flip {c.regime_start_ns}")
        r = F.simulate_trade_arrays(
            ts, opens, highs, lows, int(c.entry_fill_ts), float(c.entry_px),
            int(c.entry_direction), float(c.atr_at_checkpoint), align_ts,
            int(scheduled))
        out.append({
            "year": int(c.year), "threshold": float(c.threshold),
            "regime_start_ns": int(c.regime_start_ns),
            "signal_decision_ts": int(c.signal_decision_ts),
            "entry_fill_ts": int(c.entry_fill_ts), "entry_px": float(c.entry_px),
            "atr": float(c.atr_at_checkpoint),
            "exit_reason": r["exit_reason"], "exit_ts": r["exit_fill_ts"],
            "exit_px": r["exit_fill_px"], "net_pnl": r["net_pnl_usd"],
            "reached_aligning_flip": r["reached_aligning_flip"],
            "hold_s": (r["exit_fill_ts"] - int(c.entry_fill_ts)) / 1e9,
            "time_to_align_s": ((align_ts - int(c.entry_fill_ts)) / 1e9
                                if r["reached_aligning_flip"] else np.nan)})
    return pd.DataFrame(out)


def pf(p):
    loss = -p[p < 0].sum()
    return float(p[p > 0].sum() / loss) if loss > 0 else np.nan


def dd(p):
    eq = np.concatenate(([0.0], p.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(eq) - eq))


def metrics(df: pd.DataFrame, tau: float, split: str, basis: str) -> dict:
    p = df.sort_values("exit_ts")
    pnl = p.net_pnl.astype(float)
    w, l = pnl[pnl > 0], pnl[pnl < 0]
    er = p.exit_reason
    n = len(p)
    return {
        "threshold": tau, "basis": basis, "split": split, "trades": n,
        "net_pnl": float(pnl.sum()), "per_trade": float(pnl.mean()) if n else np.nan,
        "gross_profit": float(w.sum()), "gross_loss": float(l.sum()),
        "profit_factor": pf(pnl), "win_rate": float((pnl > 0).mean()) if n else np.nan,
        "avg_winner": float(w.mean()) if len(w) else np.nan,
        "avg_loser": float(l.mean()) if len(l) else np.nan,
        "max_closed_dd": dd(pnl), "median_hold_s": float(p.hold_s.median()) if n else np.nan,
        "median_time_to_align_s": float(p.time_to_align_s.dropna().median())
        if p.time_to_align_s.notna().any() else np.nan,
        "pre_align_stop_rate": float((er == "preflip_policy_stop").mean()) if n else np.nan,
        "timeout_rate": float((er == "confirmation_timeout_exit").mean()) if n else np.nan,
        "post_align_stop_rate": float((er == "original_stop_after_aligned_flip").mean()) if n else np.nan,
        "opposing_flip_rate": float((er == "original_opposing_flip_exit").mean()) if n else np.nan,
        "opposing_flip_pnl": float(p.loc[er == "original_opposing_flip_exit", "net_pnl"].sum()),
        "exit_reason_counts": er.value_counts().to_dict(),
        "exit_reason_pnl": {r: float(g.net_pnl.sum()) for r, g in p.groupby("exit_reason")},
    }


def entry_timing(low: pd.DataFrame, ctrl: pd.DataFrame, tau: float) -> tuple:
    """Match lower-threshold trades to control by regime; bucket + diagnose."""
    c = ctrl.set_index("regime_start_ns")
    rows, buckets = [], {}
    low_regimes = set(low.regime_start_ns)
    ctrl_regimes = set(ctrl.regime_start_ns)
    for t in low.itertuples(index=False):
        rs = int(t.regime_start_ns)
        if rs in c.index:
            cc = c.loc[rs]
            dt = (int(t.entry_fill_ts) - int(cc.entry_fill_ts)) / 1e9
            # short fade: higher entry px is better (more room)
            px_impr = float(t.entry_px) - float(cc.entry_px)
            bucket = ("matched_earlier" if int(t.entry_fill_ts) < int(cc.entry_fill_ts)
                      else "matched_same" if int(t.entry_fill_ts) == int(cc.entry_fill_ts)
                      else "matched_later")
            preempt = bool(t.exit_reason == "preflip_policy_stop"
                           and int(t.exit_ts) < int(cc.entry_fill_ts))
            rows.append({
                "threshold": tau, "regime_start_ns": rs, "bucket": bucket,
                "entry_time_delta_s": dt, "entry_px_improvement": px_impr,
                "entry_px_improvement_atr": px_impr / float(t.atr),
                "entered_before_control": int(t.entry_fill_ts) < int(cc.entry_fill_ts),
                "low_net_pnl": float(t.net_pnl), "control_net_pnl": float(cc.net_pnl),
                "low_exit_reason": t.exit_reason, "control_exit_reason": cc.exit_reason,
                "low_reached_align": bool(t.reached_aligning_flip),
                "low_prestop_before_control_entry": preempt})
        else:
            rows.append({
                "threshold": tau, "regime_start_ns": rs, "bucket": "added",
                "entry_time_delta_s": np.nan, "entry_px_improvement": np.nan,
                "entry_px_improvement_atr": np.nan, "entered_before_control": np.nan,
                "low_net_pnl": float(t.net_pnl), "control_net_pnl": np.nan,
                "low_exit_reason": t.exit_reason, "control_exit_reason": None,
                "low_reached_align": bool(t.reached_aligning_flip),
                "low_prestop_before_control_entry": False})
    for rs in (ctrl_regimes - low_regimes):
        cc = c.loc[rs]
        rows.append({"threshold": tau, "regime_start_ns": int(rs),
                     "bucket": "control_missed", "low_net_pnl": np.nan,
                     "control_net_pnl": float(cc.net_pnl),
                     "control_exit_reason": cc.exit_reason})
    td = pd.DataFrame(rows)
    for name, g in td.groupby("bucket"):
        pnl = g.low_net_pnl.dropna() if name != "control_missed" else g.control_net_pnl.dropna()
        rc = g.low_exit_reason if name != "control_missed" else g.control_exit_reason
        buckets[name] = {
            "count": int(len(g)), "pnl": float(pnl.sum()),
            "per_trade": float(pnl.mean()) if len(pnl) else np.nan,
            "exit_reason_counts": rc.value_counts().to_dict(),
            "median_entry_time_delta_s": float(g.entry_time_delta_s.dropna().median())
            if "entry_time_delta_s" in g and g.entry_time_delta_s.notna().any() else np.nan,
            "median_entry_px_improvement_atr": float(g.entry_px_improvement_atr.dropna().median())
            if "entry_px_improvement_atr" in g and g.entry_px_improvement_atr.notna().any() else np.nan,
            "prestop_before_control_entry": int(g.get("low_prestop_before_control_entry",
                                                       pd.Series(dtype=bool)).sum())}
    return td, buckets


def monthly(all_trades: pd.DataFrame) -> pd.DataFrame:
    g = all_trades.copy()
    g["month"] = pd.to_datetime(g.entry_fill_ts, unit="ns", utc=True).dt.strftime("%Y-%m")
    return g.groupby(["threshold", "month"]).agg(
        trades=("net_pnl", "size"), net_pnl=("net_pnl", "sum")).reset_index()


def decide(summary: pd.DataFrame) -> str:
    """Decision anchors on the DEPLOYABLE candidate basis (what a live lower-tau
    strategy would actually trade: all first-crossings). The fixed-807 overlay
    is a hindsight-filtered diagnostic pocket (its regime set is only knowable
    from the executed higher-threshold run) that isolates PURE entry timing on
    the confirmed 807 regimes; it is used to tell a genuine entry-timing
    improvement apart from mere added-trade volume / false starts."""
    cand = summary[(summary.basis == "candidate") & (summary.split == "combined")].set_index("threshold")
    fx = summary[(summary.basis == "fixed807") & (summary.split == "combined")].set_index("threshold")
    ctrl_c, ctrl_f = cand.loc[CONTROL], fx.loc[CONTROL]
    beats = cand[(cand.index < CONTROL) & (cand.net_pnl > ctrl_c.net_pnl)]
    if beats.empty:
        return "CURRENT_THRESHOLD_STILL_BEST"
    for tau, r in beats.sort_index(ascending=False).iterrows():
        # Is the deployable candidate-basis gain from better entry timing, or
        # just from added trades? The fixed-807 overlay (same regimes) answers:
        # if earlier entry does NOT help the fixed pocket, the candidate gain is
        # added volume / false starts, not entry quality.
        if fx.loc[tau, "net_pnl"] <= ctrl_f.net_pnl:
            return "EARLIER_THRESHOLD_ADDS_TOO_MANY_FALSE_STARTS"
        cy = summary[(summary.basis == "candidate") & (summary.threshold == tau)
                     & (summary.split.isin(["2025", "2026"]))].set_index("split")
        cc = summary[(summary.basis == "candidate") & (summary.threshold == CONTROL)
                     & (summary.split.isin(["2025", "2026"]))].set_index("split")
        if not all(cy.loc[sp, "net_pnl"] > cc.loc[sp, "net_pnl"] for sp in ("2025", "2026")):
            return "EARLIER_THRESHOLD_UNSTABLE_BY_YEAR"
        if r.max_closed_dd > ctrl_c.max_closed_dd:
            return "EARLIER_THRESHOLD_IMPROVES_ENTRY_BUT_HURTS_DD"
        return "EARLIER_THRESHOLD_PROMISING"
    return "CURRENT_THRESHOLD_STILL_BEST"


def main() -> None:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    filt = policy["filter"]
    cand_trades, fixed_trades, all_summary, all_timing = [], [], [], []
    gate_c, gate_f = {}, {}
    for year in (2025, 2026):
        raw = pd.read_parquet(RAW_1S[year],
                              columns=["open", "high", "low", "close", "volume"])
        validate_raw_bars(raw)
        ts = raw.index.view(np.int64)
        opens, highs, lows = (raw[c].to_numpy(float) for c in ("open", "high", "low"))
        stream = load_checkpoint_stream(year, policy)
        next_ends = canonical_regime_timeline(year, raw).set_index(
            "regime_start_ns")["regime_end_ns"].to_dict()
        frozen = pd.read_parquet(SCHED_DIR / f"short_rth_schedule_{year}.parquet")
        executed_regimes = set(frozen.regime_start_ns.astype(np.int64))
        for tau in THRESHOLDS:
            entries = generate_entries(year, raw, stream, tau, filt)
            if tau == CONTROL:
                gate_c[year] = gate_candidate(year, entries)
            tr = replay(entries, ts, opens, highs, lows, next_ends)
            tr["basis"] = "candidate"
            cand_trades.append(tr)
            fx = entries[entries.regime_start_ns.isin(executed_regimes)]
            ftr = replay(fx, ts, opens, highs, lows, next_ends)
            ftr["basis"] = "fixed807"
            if tau == CONTROL:
                gate_f[year] = gate_fixed807(year, ftr)
            fixed_trades.append(ftr)
    trades = pd.concat(cand_trades + fixed_trades, ignore_index=True)
    cand_all = trades[trades.basis == "candidate"]
    ctrl_cand = cand_all[cand_all.threshold == CONTROL]

    for basis in ("candidate", "fixed807"):
        for tau in THRESHOLDS:
            sub = trades[(trades.threshold == tau) & (trades.basis == basis)]
            comb = metrics(sub, tau, "combined", basis)
            if basis == "candidate" and tau != CONTROL:
                td, buckets = entry_timing(sub, ctrl_cand, tau)
                all_timing.append(td)
                comb["entry_timing_buckets"] = buckets
            all_summary.append(comb)
            for y in (2025, 2026):
                all_summary.append(metrics(sub[sub.year == y], tau, str(y), basis))
    summary = pd.DataFrame(all_summary)
    timing = pd.concat(all_timing, ignore_index=True) if all_timing else pd.DataFrame()
    gate = {"candidate_basis": gate_c, "fixed807_basis": gate_f}
    decision = decide(summary)

    trades.to_parquet(RESULTS / "w4_short_rth_threshold_ladder_results.parquet", index=False)
    timing.to_parquet(RESULTS / "w4_short_rth_threshold_ladder_trade_diffs.parquet", index=False)
    timing.to_parquet(RESULTS / "w4_short_rth_threshold_ladder_entry_timing.parquet", index=False)
    monthly(trades).to_csv(RESULTS / "w4_short_rth_threshold_ladder_monthly.csv", index=False)
    summary.drop(columns=["exit_reason_counts", "exit_reason_pnl",
                          "entry_timing_buckets"], errors="ignore").to_parquet(
        WORK / "summary_flat.parquet", index=False)

    manifest = {
        "study": "fable5_short_rth_threshold_ladder",
        "decision": decision,
        "w4_score_source": "CODEX_5_X_repaired_w4_scores_{year}.parquet (not retrained)",
        "thresholds": THRESHOLDS, "control": CONTROL,
        "rth": "08:30-15:00 America/Chicago (entry only)",
        "policy_a": {"pre_stop_atr": 1.25, "timeout_s": 300, "post_stop_atr": 1.50,
                     "atr_source": "atr_at_checkpoint"},
        "cost": {"multiplier": MULT, "round_trip_usd": COST, "quantity": 1},
        "control_parity": gate,
        "basis_note": ("candidate = first-crossing short-RTH per prevailing-long "
                       "regime (872 control); fixed807 = the globally "
                       "one-position-executed confirmed pocket (807 control, "
                       "reproduces +$27,013)"),
        "population_by_threshold_basis": {
            b: {str(t): int(((trades.threshold == t) & (trades.basis == b)).sum())
                for t in THRESHOLDS} for b in ("candidate", "fixed807")},
        "summary": [ {k: v for k, v in r.items()
                      if k not in ("exit_reason_counts",)} for r in all_summary],
        "policy_sha256": sha256_file(POLICY_PATH),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "schedule_sha256": {str(y): sha256_file(SCHED_DIR / f"short_rth_schedule_{y}.parquet")
                            for y in (2025, 2026)},
    }
    (RESULTS / "w4_short_rth_threshold_ladder_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print("DECISION:", decision)
    print("control parity:", json.dumps(gate, default=str))
    for basis in ("candidate", "fixed807"):
        show = summary[(summary.split == "combined") & (summary.basis == basis)][
            ["threshold", "trades", "net_pnl", "per_trade", "profit_factor",
             "max_closed_dd", "pre_align_stop_rate", "timeout_rate",
             "opposing_flip_rate", "opposing_flip_pnl"]]
        print(f"\n=== {basis} basis (combined) ===")
        print(show.to_string(index=False))
        for y in ("2025", "2026"):
            yy = summary[(summary.split == y) & (summary.basis == basis)][
                ["threshold", "trades", "net_pnl", "max_closed_dd"]]
            print(f"  --- {basis} {y} ---")
            print(yy.to_string(index=False))


if __name__ == "__main__":
    main()
