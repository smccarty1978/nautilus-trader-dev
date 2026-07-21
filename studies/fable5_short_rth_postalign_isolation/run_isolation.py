"""Offline isolation of the 1.50 ATR post-alignment stop on the short-RTH pocket.

H0 = current Policy A (1.25 pre stop / 300s timeout / 1.50 post-alignment stop
/ opposing-flip exit). H1 = identical EXCEPT the post-alignment stop is removed
(after bearish alignment, hold to the opposing bullish flip). Both run in the
same fixture-parity-tested offline 1s-OHLC Policy A engine over the identical
frozen 807-entry short-RTH schedule, so they differ ONLY in the post-align stop.

H0 is reconciled trade-for-trade against the frozen offline Policy A benchmark
(codex_5_w4_fade_confirmation_clock_isolation) as the baseline-reproduction gate.

1-second OHLC research simulation (offline), not NT event-driven or tick-level.
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

import fable5_common as F  # noqa: E402  (simulate helpers, cost consts)
from CODEX_5_X_common import RAW_1S, sha256_file  # noqa: E402
from CODEX_5_X_run_established_fade import canonical_regime_timeline  # noqa: E402

NS = 1_000_000_000
MULT, COST = 20.0, 10.0
PRE_ATR, POST_ATR, TIMEOUT_NS = 1.25, 1.50, 300 * NS
SCHED_DIR = ROOT / "studies" / "fable5_nt_short_rth_policy_a" / "_work"
ISOLATION = (ROOT / "studies" / "codex_5_w4_fade_confirmation_clock_isolation"
             / "results" / "isolation_trade_diffs.parquet")
POLICY_A_ID = "POLICY_A_COMBINED_1P25_300S"


def simulate(ts, opens, highs, lows, entry_ts, entry, direction, atr,
             align_ts, scheduled_decision, post_stop_enabled: bool) -> dict:
    """Policy A path replay. Byte-identical to the audited
    fable5_common.simulate_trade_arrays when post_stop_enabled=True; when
    False the post-alignment stop is never checked (H1: hold to opposing flip)."""
    timeout_ts = entry_ts + TIMEOUT_NS
    start = int(np.searchsorted(ts, entry_ts, side="left"))
    scheduled_i = int(np.searchsorted(ts, scheduled_decision, side="left"))
    if start >= len(ts) or int(ts[start]) != entry_ts or scheduled_i >= len(ts):
        raise RuntimeError("invalid entry or scheduled exit boundary")
    scheduled_fill_ts = int(ts[scheduled_i])
    pre_stop = entry - direction * PRE_ATR * atr
    post_stop = entry - direction * POST_ATR * atr
    aligned, timeout_pending = False, False
    exit_ts = exit_px = reason = None
    mae_after_align = 0.0
    for i in range(start, scheduled_i + 1):
        now = int(ts[i])
        if aligned:
            # ADVERSE move after alignment: for a short (dir=-1) price UP
            # (highs) is against us; for a long, price DOWN (lows) is.
            adv = ((highs[i] - entry) / atr if direction == -1
                   else (entry - lows[i]) / atr)
            mae_after_align = max(mae_after_align, adv)
        if not aligned and now >= align_ts and align_ts <= timeout_ts:
            aligned = True
        if timeout_pending and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if not aligned and now > timeout_ts:
            exit_ts, exit_px, reason = now, opens[i], "confirmation_timeout_exit"
            break
        if now >= scheduled_fill_ts:
            exit_ts, exit_px, reason = now, opens[i], "original_opposing_flip_exit"
            break
        if not aligned and now >= align_ts:
            aligned = True
        if now == timeout_ts and not aligned:
            timeout_pending = True
        stop = post_stop if aligned else pre_stop
        stop_active = (not aligned) or post_stop_enabled
        stop_reason = ("original_stop_after_aligned_flip" if aligned
                       else "preflip_policy_stop")
        if stop_active and F.touched_stop(direction, stop, highs[i], lows[i]):
            exit_ts = now
            exit_px = F.stop_fill(direction, stop, opens[i])
            reason = stop_reason
            break
    if exit_ts is None:
        raise RuntimeError("trade replay ended without exit")
    pts = direction * (float(exit_px) - entry)
    return {"aligned": aligned, "align_ts": int(align_ts) if aligned else None,
            "exit_ts": int(exit_ts), "exit_px": float(exit_px),
            "exit_reason": reason, "gross_pnl_pts": pts,
            "net_pnl": pts * MULT - COST,
            "hold_s": (int(exit_ts) - entry_ts) / 1e9,
            "mae_after_align_atr": float(mae_after_align)}


def load_schedule(year: int) -> pd.DataFrame:
    d = pd.read_parquet(SCHED_DIR / f"short_rth_schedule_{year}.parquet")
    return d.sort_values("target_fill_ts").reset_index(drop=True)


def run_year(year: int) -> pd.DataFrame:
    sched = load_schedule(year)
    raw = pd.read_parquet(RAW_1S[year],
                          columns=["open", "high", "low", "close", "volume"])
    from CODEX_5_X_run_established_fade import validate_raw_bars
    validate_raw_bars(raw)
    ts = raw.index.view(np.int64)
    opens = raw.open.to_numpy(float)
    highs = raw.high.to_numpy(float)
    lows = raw.low.to_numpy(float)
    timeline = canonical_regime_timeline(year, raw)
    next_ends = timeline.set_index("regime_start_ns")["regime_end_ns"].to_dict()

    rows = []
    for c in sched.itertuples(index=False):
        entry_ts = int(c.target_fill_ts)
        direction = int(c.entry_direction)
        atr = float(c.atr_at_checkpoint)
        align_ts = int(c.recon_confirm_flip_ns)
        scheduled = next_ends.get(align_ts)
        if scheduled is None:
            raise RuntimeError(f"missing opposing flip for {c.regime_start_ns}")
        start = int(np.searchsorted(ts, entry_ts, side="left"))
        entry = float(opens[start])
        h0 = simulate(ts, opens, highs, lows, entry_ts, entry, direction, atr,
                      align_ts, int(scheduled), post_stop_enabled=True)
        h1 = simulate(ts, opens, highs, lows, entry_ts, entry, direction, atr,
                      align_ts, int(scheduled), post_stop_enabled=False)
        rows.append({
            "year": year, "regime_start_ns": int(c.regime_start_ns),
            "entry_fill_ts": entry_ts, "entry_px": entry, "atr": atr,
            "direction": direction,
            "h0_exit_ts": h0["exit_ts"], "h0_exit_px": h0["exit_px"],
            "h0_exit_reason": h0["exit_reason"], "h0_net_pnl": h0["net_pnl"],
            "h0_hold_s": h0["hold_s"], "h0_aligned": h0["aligned"],
            "h1_exit_ts": h1["exit_ts"], "h1_exit_px": h1["exit_px"],
            "h1_exit_reason": h1["exit_reason"], "h1_net_pnl": h1["net_pnl"],
            "h1_hold_s": h1["hold_s"],
            "h1_mae_after_align_atr": h1["mae_after_align_atr"],
            "pnl_delta_h1_minus_h0": h1["net_pnl"] - h0["net_pnl"],
        })
    return pd.DataFrame(rows)


def reconcile_h0(year: int, df: pd.DataFrame) -> dict:
    off = pd.read_parquet(ISOLATION)
    off = off[(off.policy_id == POLICY_A_ID) & (off.year == year)
              & (off.trade_direction == "short_fade") & (off.session == "RTH")]
    off = off.sort_values("entry_fill_ts").reset_index(drop=True)
    mine = df.sort_values("entry_fill_ts").reset_index(drop=True)
    if len(mine) != len(off):
        raise RuntimeError(f"{year} H0 count {len(mine)} != offline {len(off)}")
    if mine.entry_fill_ts.duplicated().any() or off.entry_fill_ts.duplicated().any():
        raise RuntimeError(f"{year} duplicate entry_fill_ts; positional reconcile unsafe")
    m = 0
    m += int((mine.entry_fill_ts.to_numpy(np.int64)
              != off.entry_fill_ts.to_numpy(np.int64)).sum())
    m += int((mine.h0_exit_ts.to_numpy(np.int64)
              != off.new_exit_fill_ts.to_numpy(np.int64)).sum())
    m += int((~np.isclose(mine.h0_exit_px, off.new_exit_fill_px, rtol=0, atol=1e-9)).sum())
    m += int((mine.h0_exit_reason.to_numpy() != off.new_exit_reason.to_numpy()).sum())
    m += int((~np.isclose(mine.h0_net_pnl, off.new_net_pnl_usd, rtol=0, atol=1e-6)).sum())
    if m:
        raise RuntimeError(f"{year} H0 baseline reconciliation mismatch: {m}")
    return {"year": year, "trades": len(mine), "mismatches": 0,
            "h0_net_pnl": float(mine.h0_net_pnl.sum()),
            "offline_net_pnl": float(off.new_net_pnl_usd.sum())}


def pf(pnl: pd.Series) -> float:
    loss = -pnl[pnl < 0].sum()
    return float(pnl[pnl > 0].sum() / loss) if loss > 0 else np.nan


def dd(pnl: pd.Series) -> float:
    eq = np.concatenate(([0.0], pnl.cumsum().to_numpy(float)))
    return float(np.max(np.maximum.accumulate(eq) - eq))


def variant_metrics(df: pd.DataFrame, arm: str, label: str) -> dict:
    p = df.sort_values(f"{arm}_exit_ts")
    pnl = p[f"{arm}_net_pnl"].astype(float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    return {"variant": label, "split": df.name if hasattr(df, "name") else "",
            "trades": int(len(p)), "net_pnl": float(pnl.sum()),
            "per_trade": float(pnl.mean()), "gross_profit": float(wins.sum()),
            "gross_loss": float(losses.sum()), "profit_factor": pf(pnl),
            "win_rate": float((pnl > 0).mean()),
            "avg_winner": float(wins.mean()) if len(wins) else np.nan,
            "avg_loser": float(losses.mean()) if len(losses) else np.nan,
            "max_closed_dd": dd(pnl), "median_hold_s": float(p[f"{arm}_hold_s"].median()),
            "exit_reason_counts": p[f"{arm}_exit_reason"].value_counts().to_dict(),
            "exit_reason_pnl": {r: float(g[f"{arm}_net_pnl"].sum())
                                for r, g in p.groupby(f"{arm}_exit_reason")}}


def summarize(all_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    splits = [("combined", all_df)] + [(str(y), all_df[all_df.year == y])
                                        for y in (2025, 2026)]
    for name, g in splits:
        for arm, label in (("h0", "H0_current"), ("h1", "H1_no_post_stop")):
            r = variant_metrics(g, arm, label)
            r["split"] = name
            rows.append(r)
    return pd.DataFrame(rows)


def attribution(all_df: pd.DataFrame) -> dict:
    cohort = all_df[all_df.h0_exit_reason == "original_stop_after_aligned_flip"].copy()
    n = len(cohort)
    delta = cohort.pnl_delta_h1_minus_h0
    improved = cohort[delta > 1e-6]
    worsened = cohort[delta < -1e-6]
    recovered = cohort[(cohort.h0_net_pnl < 0) & (cohort.h1_net_pnl > 0)]
    large_winner = cohort[cohort.h1_net_pnl >= 500.0]  # >=25 pts
    time_to_flip_s = ((cohort.h1_exit_ts - cohort.h0_exit_ts) / 1e9)
    # any non-stop_after H0 trade that changes under H1 (should be none)
    non_cohort = all_df[all_df.h0_exit_reason != "original_stop_after_aligned_flip"]
    changed = non_cohort[np.abs(non_cohort.pnl_delta_h1_minus_h0) > 1e-6]
    return {
        "h0_stop_after_flip_trades": int(n),
        "h0_total_pnl": float(cohort.h0_net_pnl.sum()),
        "h1_total_pnl_at_opposing_flip": float(cohort.h1_net_pnl.sum()),
        "delta_total": float(delta.sum()),
        "count_improved": int(len(improved)), "count_worsened": int(len(worsened)),
        "count_unchanged": int((delta.abs() <= 1e-6).sum()),
        "count_loss_got_larger": int(((cohort.h1_net_pnl < cohort.h0_net_pnl)
                                      & (cohort.h1_net_pnl < 0)).sum()),
        "count_recovered_to_profit": int(len(recovered)),
        "count_became_large_winner_ge_500usd": int(len(large_winner)),
        "avg_h0_result": float(cohort.h0_net_pnl.mean()) if n else np.nan,
        "avg_h1_result": float(cohort.h1_net_pnl.mean()) if n else np.nan,
        "median_h1_result": float(cohort.h1_net_pnl.median()) if n else np.nan,
        "median_mae_after_h0_stop_atr": float(cohort.h1_mae_after_align_atr.median())
        if n else np.nan,
        "max_mae_after_h0_stop_atr": float(cohort.h1_mae_after_align_atr.max())
        if n else np.nan,
        "median_time_h0stop_to_opposing_flip_s": float(time_to_flip_s.median())
        if n else np.nan,
        "non_stop_after_trades_changed_under_h1": int(len(changed)),
    }


def monthly(all_df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for arm, label in (("h0", "H0_current"), ("h1", "H1_no_post_stop")):
        g = all_df.copy()
        g["month"] = pd.to_datetime(g.entry_fill_ts, unit="ns", utc=True
                                    ).dt.tz_convert("UTC").dt.strftime("%Y-%m")
        agg = g.groupby("month").agg(
            trades=(f"{arm}_net_pnl", "size"),
            net_pnl=(f"{arm}_net_pnl", "sum")).reset_index()
        agg["variant"] = label
        out.append(agg)
    return pd.concat(out, ignore_index=True)


def decide(summary: pd.DataFrame) -> str:
    c = summary[summary.split == "combined"].set_index("variant")
    h0, h1 = c.loc["H0_current"], c.loc["H1_no_post_stop"]
    pnl_up = h1.net_pnl > h0.net_pnl
    dd_down = h1.max_closed_dd < h0.max_closed_dd
    if pnl_up and dd_down:
        return "POSTALIGN_STOP_HURTS"
    if pnl_up and not dd_down:
        return "POSTALIGN_STOP_PNL_UP_DD_UP"
    if not pnl_up and dd_down:
        return "POSTALIGN_STOP_RISK_CONTROL_ONLY"
    return "POSTALIGN_STOP_HELPS"


def main() -> None:
    recon, frames = {}, []
    for year in (2025, 2026):
        df = run_year(year)
        recon[year] = reconcile_h0(year, df)
        frames.append(df)
    all_df = pd.concat(frames, ignore_index=True)
    if len(all_df) != 807:
        raise RuntimeError(f"population {len(all_df)} != 807")
    summary = summarize(all_df)
    attr = attribution(all_df)
    mon = monthly(all_df)
    decision = decide(summary)

    all_df.to_parquet(RESULTS / "nt_short_rth_postalign_stop_isolation_results.parquet", index=False)
    all_df[["year", "regime_start_ns", "entry_fill_ts", "entry_px", "atr",
            "h0_exit_reason", "h0_net_pnl", "h1_exit_reason", "h1_net_pnl",
            "pnl_delta_h1_minus_h0", "h1_mae_after_align_atr"]].to_parquet(
        RESULTS / "nt_short_rth_postalign_stop_isolation_trade_diffs.parquet", index=False)
    mon.to_csv(RESULTS / "nt_short_rth_postalign_stop_isolation_monthly.csv", index=False)
    summary.to_parquet(WORK / "summary.parquet", index=False)

    manifest = {
        "study": "fable5_short_rth_postalign_isolation",
        "engine": "offline 1s-OHLC Policy A (fable5_common.simulate_trade_arrays parity)",
        "decision": decision,
        "variants": {"H0": "current Policy A (1.50 ATR post-align stop)",
                     "H1": "no post-align stop; hold to opposing flip"},
        "population": {"combined": int(len(all_df)),
                       "2025": int((all_df.year == 2025).sum()),
                       "2026": int((all_df.year == 2026).sum())},
        "rth": "08:30-15:00 America/Chicago (entry only; frozen schedule)",
        "cost": {"multiplier": MULT, "round_trip_usd": COST, "quantity": 1},
        "fill_model": "offline next-open entry; stop at trigger (gap->open); opposing flip next-open",
        "h0_baseline_reconciliation": recon,
        "attribution_stop_after_flip": attr,
        "schedule_sha256": {str(y): sha256_file(SCHED_DIR / f"short_rth_schedule_{y}.parquet")
                            for y in (2025, 2026)},
        "runner_sha256": sha256_file(Path(__file__).resolve()),
    }
    (RESULTS / "nt_short_rth_postalign_stop_isolation_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    (WORK / "attribution.json").write_text(json.dumps(attr, indent=2, default=str),
                                           encoding="utf-8")
    print(json.dumps({"decision": decision, "recon": recon,
                      "attribution": attr}, indent=2, default=str))
    print(summary[["split", "variant", "trades", "net_pnl", "per_trade",
                   "profit_factor", "max_closed_dd"]].to_string(index=False))


if __name__ == "__main__":
    main()
