"""Run the single frozen Stage-2 policy under the explicit 1s OHLC contract.

This is a causal sequential research replay, not NT-native executable
validation.  It deliberately avoids the NT-native bar matcher whose fill
contract was rejected in the preceding D10 study.
"""
from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np
import pandas as pd

from common import FLIP_ATLAS, NS, PRIOR, RAW_1S, RESULTS, STUDY, is_rth

POLICY_PATH = STUDY / "stage2_frozen_policy.json"
SCORES_PATH = PRIOR / "causal_scores.parquet"
PRE_EXEC_AUDIT = STUDY / "audit" / "stage2_pre_execution_audit.md"
WINDOWS = {
    2025: (pd.Timestamp("2025-03-01", tz="UTC").value,
           pd.Timestamp("2025-12-31", tz="UTC").value),
    2026: (pd.Timestamp("2026-01-01", tz="UTC").value,
           pd.Timestamp("2026-04-30", tz="UTC").value),
}


def load_policy() -> dict:
    p = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert p["frozen_before_monetization_results"] is True
    assert p["research_contract"] == "EXPLICIT_NEXT_OPEN_OHLC_RESEARCH_CONTRACT"
    assert p["stop_atr"] == 1.5
    assert p["optional_secondary_exit"] == "not implemented"
    return p


def policy_sha256() -> str:
    return hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()


def require_passed_audit() -> None:
    assert PRE_EXEC_AUDIT.exists(), "missing Stage-2 pre-execution audit"
    text = PRE_EXEC_AUDIT.read_text(encoding="utf-8")
    assert "**Status:** **PASS" in text, "Stage-2 pre-execution audit is not PASS"
    assert "0 CRITICAL" in text and "0 WARNING" in text, \
        "Stage-2 audit does not report zero findings"


def require_clean_2025_predecessor() -> None:
    path = RESULTS / "stage2_reconciliation_2025.json"
    assert path.exists(), "2026 is sealed until clean 2025 reconciliation exists"
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["policy_sha256"] == policy_sha256(), "2025 policy hash mismatch"
    assert rec["blocking_errors"] == 0, "2025 reconciliation is not clean"
    assert rec["closure_residual"] == 0, "2025 candidate accounting is not closed"


def load_regimes(year: int) -> pd.DataFrame:
    """Regime identities from a fresh per-year RegimeEngine run.

    The flip_context_atlas F1 `direction` column is 100% NaN for 2021-2025
    and its `regime` fallback carries ~25% sign flips where comparable
    (Stage-1 pass-2 audit CRITICAL) — the same fix applied to Stage 1.
    Direction is parity-checked (fail-fast) against the prior study's
    causal score stream. The trailing open regime is retained with
    regime_end_ns = data end and end_censored=True (it may originate
    candidates; survivors are right-censored, per the audited contract).
    """
    import sys as _sys
    from common import ROOT
    up = str(ROOT / "studies" / "regime_sequence_chop_context")
    if up not in _sys.path:
        _sys.path.insert(0, up)
    from reproduce_regimes import aggregate_and_run_regimes

    raw = pd.read_parquet(RAW_1S[year],
                          columns=["open", "high", "low", "close", "volume"])
    data_end_ns = int(raw.index.view(np.int64)[-1]) + NS
    df_1m = aggregate_and_run_regimes(raw, "1m").sort_values("close_ts")
    del raw
    prev = df_1m["regime"].shift(1).fillna(0).astype(int)
    flips = df_1m[(df_1m["regime"] != 0) & (prev != 0)
                  & (df_1m["regime"] != prev)]
    frows = list(flips.itertuples())
    rows = []
    for i, r in enumerate(frows):
        censored = i + 1 >= len(frows)
        rows.append({
            "regime_start_ns": int(r.close_ts),
            "regime_end_ns": (int(frows[i + 1].close_ts) if not censored
                              else data_end_ns),
            "direction": int(r.regime),
            "atr": float(r.atr),
            "end_censored": censored,
        })
    d = pd.DataFrame(rows).sort_values("regime_start_ns").reset_index(drop=True)
    d["year"] = year
    assert not d.duplicated("regime_start_ns").any()

    # fail-fast direction parity vs the prior study's causal score stream
    sc = pd.read_parquet(SCORES_PATH,
                         columns=["regime_start_ns", "direction", "year"])
    sc = sc[sc["year"] == year].drop_duplicates("regime_start_ns")
    par = d.merge(sc, on="regime_start_ns", how="inner",
                  suffixes=("", "_score"))
    n_mm = int((par["direction"] != par["direction_score"]).sum())
    assert n_mm == 0, (f"direction parity failure vs score stream: {n_mm} "
                       f"mismatches in {year}")
    print(f"  regimes {year}: {len(d):,} (1 censored tail retained); "
          f"direction parity {len(par):,} matched, 0 mismatches")
    return d


def progress_window_counts(running_mfe: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """Causal count of distinct new-progress windows at every completed bar."""
    out = np.zeros(len(ts), dtype=np.int16)
    if not len(ts):
        return out
    count = 0
    last_extreme_ts: int | None = None
    prev = -np.inf
    for i, value in enumerate(running_mfe):
        if value > prev + 1e-12:
            if last_extreme_ts is None or int(ts[i]) - last_extreme_ts >= 120 * NS:
                count += 1
            last_extreme_ts = int(ts[i])
            prev = float(value)
        out[i] = count
    return out


def build_candidates(year: int, policy: dict, raw: pd.DataFrame,
                     regimes: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    start_win, end_win = WINDOWS[year]
    scores = pd.read_parquet(SCORES_PATH)
    scores = scores[(scores["year"] == year) & scores["score_valid"]
                    & scores["w4_score"].notna()].copy()
    scores = scores.sort_values(["regime_start_ns", "observation_time"])
    groups = {int(k): g for k, g in scores.groupby("regime_start_ns", sort=False)}

    ts = raw.index.view(np.int64)
    highs = raw["high"].to_numpy(dtype=float)
    lows = raw["low"].to_numpy(dtype=float)
    closes = raw["close"].to_numpy(dtype=float)
    filt = policy["filter"]
    threshold = float(policy["w4_threshold"])
    rows: list[dict] = []
    audit: list[dict] = []

    for r in regimes.itertuples(index=False):
        g = groups.get(int(r.regime_start_ns))
        if g is None or len(g) < 2:
            continue
        a = int(np.searchsorted(ts, r.regime_start_ns, side="left"))
        b = int(np.searchsorted(ts, r.regime_end_ns, side="left"))
        if b <= a or not np.isfinite(r.atr) or r.atr <= 0:
            audit.append({"regime_start_ns": int(r.regime_start_ns),
                          "decision_ts": None,
                          "reason": "invalid_regime_atr_or_empty_path"})
            continue
        anchor_i = a - 1
        if anchor_i < 0:
            continue
        anchor = float(closes[anchor_i])
        if r.direction == 1:
            running_mfe = np.maximum.accumulate((highs[a:b] - anchor) / r.atr)
        else:
            running_mfe = np.maximum.accumulate((anchor - lows[a:b]) / r.atr)
        pwin = progress_window_counts(running_mfe, ts[a:b])

        prev_score: float | None = None
        for cp in g.itertuples(index=False):
            score = float(cp.w4_score)
            crossed = prev_score is not None and prev_score < threshold <= score
            prev_score = score
            if not crossed:
                continue
            decision = int(cp.observation_time + NS)
            if not (start_win <= decision < end_win):
                continue
            if decision >= r.regime_end_ns:
                audit.append({"regime_start_ns": int(r.regime_start_ns),
                              "decision_ts": decision,
                              "reason": "cross_available_at_or_after_flip"})
                continue
            k = int(np.searchsorted(ts[a:b], decision, side="left") - 1)
            if k < 0:
                continue
            mfe = float(running_mfe[k])
            current_pnl = float(r.direction * (closes[a + k] - anchor) / r.atr)
            retained = current_pnl / mfe if mfe > 0 else np.nan
            age = (decision - r.regime_start_ns) / NS
            established = bool(
                age >= filt["regime_age_s_min"]
                and mfe >= filt["running_mfe_atr_min"]
                and int(pwin[k]) >= filt["new_progress_windows_min"]
                and retained >= filt["retained_mfe_ratio_min"]
            )
            audit.append({
                "regime_start_ns": int(r.regime_start_ns),
                "decision_ts": decision, "reason": "eligible" if established else "filter_fail",
                "age_s": age, "running_mfe_atr": mfe,
                "new_progress_windows": int(pwin[k]),
                "retained_mfe_ratio": retained, "w4_score": score,
            })
            if established:
                if not np.isfinite(cp.atr) or float(cp.atr) <= 0:
                    audit[-1]["reason"] = "invalid_trigger_atr"
                    continue
                rows.append({
                    "year": year,
                    "regime_start_ns": int(r.regime_start_ns),
                    # Integer 0 sentinel avoids float/NaN precision loss for
                    # nanosecond timestamps on right-censored regimes.
                    "confirm_flip_ns": 0 if r.end_censored else int(r.regime_end_ns),
                    "prevailing_end_censored": bool(r.end_censored),
                    "prevailing_direction": int(r.direction),
                    "entry_direction": -int(r.direction),
                    "decision_ts": decision,
                    "score_observation_ts": int(cp.observation_time),
                    "w4_score": score,
                    "atr_at_trigger": float(cp.atr),
                    "regime_age_s": age,
                    "running_mfe_atr": mfe,
                    "new_progress_windows": int(pwin[k]),
                    "retained_mfe_ratio": retained,
                    "session": "RTH" if bool(is_rth(np.array([decision]))[0]) else "ETH",
                })
                break  # one trigger per prevailing regime
    return pd.DataFrame(rows).sort_values("decision_ts"), audit


def simulate(year: int, candidates: pd.DataFrame, raw: pd.DataFrame,
             regimes: pd.DataFrame, policy: dict) -> tuple[pd.DataFrame, list[dict]]:
    ts = raw.index.view(np.int64)
    opens = raw["open"].to_numpy(dtype=float)
    highs = raw["high"].to_numpy(dtype=float)
    lows = raw["low"].to_numpy(dtype=float)
    reg_by_start = regimes.set_index("regime_start_ns")
    trades: list[dict] = []
    skipped: list[dict] = []
    busy_until = -1

    for c in candidates.itertuples(index=False):
        if c.decision_ts < busy_until:
            skipped.append({"regime_start_ns": c.regime_start_ns,
                            "decision_ts": c.decision_ts,
                            "reason": "decision_while_position_open"})
            continue
        entry_i = int(np.searchsorted(ts, c.decision_ts, side="left"))
        if entry_i >= len(ts):
            skipped.append({"regime_start_ns": c.regime_start_ns,
                            "decision_ts": c.decision_ts,
                            "reason": "no_next_available_open"})
            continue
        entry_ts = int(ts[entry_i])
        start_win, end_win = WINDOWS[year]
        has_confirming_flip = not bool(c.prevailing_end_censored)
        if has_confirming_flip and entry_ts >= c.confirm_flip_ns:
            skipped.append({"regime_start_ns": c.regime_start_ns,
                            "decision_ts": c.decision_ts,
                            "reason": "next_open_at_or_after_confirming_flip"})
            continue
        if not (start_win <= entry_ts < end_win):
            skipped.append({"regime_start_ns": c.regime_start_ns,
                            "decision_ts": c.decision_ts,
                            "reason": "next_open_outside_authorized_window"})
            continue
        # The confirming regime begins at confirm_flip_ns. Its end is the flip
        # back against the countertrade and is the scheduled exit decision.
        if has_confirming_flip and c.confirm_flip_ns not in reg_by_start.index:
            skipped.append({"regime_start_ns": c.regime_start_ns,
                            "decision_ts": c.decision_ts,
                            "reason": "no_confirmed_regime_row"})
            continue
        if has_confirming_flip:
            confirmed_row = reg_by_start.loc[c.confirm_flip_ns]
            confirmed_censored = bool(confirmed_row["end_censored"])
            exit_decision = None if confirmed_censored else int(confirmed_row["regime_end_ns"])
        else:
            # The prevailing regime itself is still open at data end. Enter
            # without conditioning on that future fact; stops remain active
            # and a survivor is right-censored before any confirming flip.
            exit_decision = None
        exit_i = len(ts) if exit_decision is None else int(
            np.searchsorted(ts, exit_decision, side="left")
        )
        exit_i = min(exit_i, len(ts))
        entry_px = float(opens[entry_i])
        stop_px = entry_px - c.entry_direction * policy["stop_atr"] * c.atr_at_trigger
        exit_reason = "data_end_censored"
        exit_ts = None
        exit_px = np.nan
        confirmed = False
        for i in range(entry_i, exit_i):
            if has_confirming_flip and ts[i] >= c.confirm_flip_ns:
                confirmed = True
            touched = lows[i] <= stop_px if c.entry_direction == 1 else highs[i] >= stop_px
            if touched:
                gapped = opens[i] <= stop_px if c.entry_direction == 1 else opens[i] >= stop_px
                exit_px = float(opens[i]) if gapped else float(stop_px)
                exit_ts = int(ts[i])
                exit_reason = "stop_after_flip" if confirmed else "stop_before_flip"
                break
        if exit_ts is None and exit_decision is not None and exit_i < len(ts):
            exit_ts = int(ts[exit_i])
            exit_px = float(opens[exit_i])
            exit_reason = "opposite_flip_against_countertrade"
        # A stop touch is only localized to its 1s bar. Conservatively prevent
        # another entry at that bar's open; a scheduled market exit is known
        # and filled at the boundary open, so a same-boundary new entry may
        # follow it.
        if exit_ts is None:
            busy_until = int(ts[-1] + NS)
        elif exit_reason.startswith("stop"):
            busy_until = int(exit_ts + NS)
        else:
            busy_until = int(exit_ts)
        gross_pts = (exit_px - entry_px) * c.entry_direction if np.isfinite(exit_px) else np.nan
        gross_usd = gross_pts * 20.0 if np.isfinite(gross_pts) else np.nan
        trades.append({
            **c._asdict(),
            "entry_fill_ts": entry_ts, "entry_fill_px": entry_px,
            "stop_px": stop_px, "stop_active_entry_bar": True,
            "realized_stop_atr": abs(entry_px - stop_px) / c.atr_at_trigger,
            "scheduled_exit_decision_ts": exit_decision,
            "exit_fill_ts": exit_ts, "exit_fill_px": exit_px,
            "exit_reason": exit_reason,
            "gross_pnl_pts": gross_pts, "gross_pnl_usd": gross_usd,
            "net_pnl_usd": gross_usd - policy["cost_rt_usd"] if np.isfinite(gross_usd) else np.nan,
            "hold_s": (exit_ts - entry_ts) / NS if exit_ts is not None else np.nan,
            "entry_fill_delay_s": (entry_ts - c.decision_ts) / NS,
            "contract": policy["research_contract"],
            "policy_sha256": policy_sha256(),
        })
    return pd.DataFrame(trades), skipped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True, choices=[2025, 2026])
    args = ap.parse_args()
    require_passed_audit()
    if args.year == 2026:
        require_clean_2025_predecessor()
    policy = load_policy()
    raw = pd.read_parquet(RAW_1S[args.year], columns=["open", "high", "low", "close"])
    regimes = load_regimes(args.year)
    candidates, trigger_audit = build_candidates(args.year, policy, raw, regimes)
    trades, skipped = simulate(args.year, candidates, raw, regimes, policy)
    candidates.to_parquet(RESULTS / f"stage2_candidates_{args.year}.parquet", index=False)
    trades.to_parquet(RESULTS / f"stage2_trades_{args.year}.parquet", index=False)
    pd.DataFrame(trigger_audit).to_parquet(
        RESULTS / f"stage2_trigger_audit_{args.year}.parquet", index=False)
    pd.DataFrame(skipped).to_parquet(
        RESULTS / f"stage2_skipped_{args.year}.parquet", index=False)
    closure_residual = len(candidates) - len(trades) - len(skipped)
    max_stop_distance_error_atr = float(
        np.abs(trades["realized_stop_atr"] - 1.5).max()
    ) if len(trades) else 0.0
    wrong_stop_distance = int(
        (~np.isclose(trades["realized_stop_atr"], 1.5, rtol=0, atol=1e-9)).sum()
    ) if len(trades) else 0
    invalid_trade_atr = int(
        ((~np.isfinite(trades["atr_at_trigger"])) | (trades["atr_at_trigger"] <= 0)).sum()
    ) if len(trades) else 0
    fill_at_or_after_flip = int(
        ((~trades["prevailing_end_censored"])
         & (trades["entry_fill_ts"] >= trades["confirm_flip_ns"])).sum()
    ) if len(trades) else 0
    start_win, end_win = WINDOWS[args.year]
    fill_outside_window = int(
        ((trades["entry_fill_ts"] < start_win) | (trades["entry_fill_ts"] >= end_win)).sum()
    ) if len(trades) else 0
    exit_before_entry = int(
        ((trades["exit_fill_ts"].notna())
         & (trades["exit_fill_ts"] < trades["entry_fill_ts"])).sum()
    ) if len(trades) else 0
    incomplete_state = int(
        (((trades["exit_reason"] == "data_end_censored") & trades["exit_fill_ts"].notna())
         | ((trades["exit_reason"] != "data_end_censored") & trades["exit_fill_ts"].isna())).sum()
    ) if len(trades) else 0
    duplicate_candidates = int(candidates["regime_start_ns"].duplicated().sum()) if len(candidates) else 0
    negative_delays = int((trades["entry_fill_delay_s"] < 0).sum()) if len(trades) else 0
    wrong_contract = int((trades["contract"] != policy["research_contract"]).sum()) if len(trades) else 0
    exit_reason_residual = len(trades) - int(trades["exit_reason"].value_counts().sum()) if len(trades) else 0
    blocking_errors = sum([
        abs(closure_residual), duplicate_candidates, negative_delays,
        wrong_contract, wrong_stop_distance, invalid_trade_atr,
        fill_at_or_after_flip, fill_outside_window, exit_before_entry,
        incomplete_state, abs(exit_reason_residual),
    ])
    reconciliation = {
            "year": args.year,
            "policy_sha256": policy_sha256(),
            "candidate_count": len(candidates),
            "trade_count": len(trades),
            "skip_count": len(skipped),
            "closure_residual": closure_residual,
            "duplicate_candidate_regimes": duplicate_candidates,
            "negative_entry_delays": negative_delays,
            "wrong_contract_rows": wrong_contract,
            "wrong_stop_distance_rows": wrong_stop_distance,
            "max_stop_distance_error_atr": max_stop_distance_error_atr,
            "invalid_trade_atr_rows": invalid_trade_atr,
            "fill_at_or_after_confirming_flip_rows": fill_at_or_after_flip,
            "fill_outside_authorized_window_rows": fill_outside_window,
            "exit_before_entry_rows": exit_before_entry,
            "incomplete_exit_or_censor_state_rows": incomplete_state,
            "exit_reason_residual": exit_reason_residual,
            "max_entry_fill_delay_s": float(trades["entry_fill_delay_s"].max()) if len(trades) else None,
            "blocking_errors": blocking_errors,
        }
    assert closure_residual == 0, "candidate accounting did not close"
    assert blocking_errors == 0, f"{blocking_errors} blocking reconciliation errors"
    (RESULTS / f"stage2_reconciliation_{args.year}.json").write_text(
        json.dumps(reconciliation, indent=2), encoding="utf-8")
    print(f"{args.year}: {len(candidates)} candidates, {len(trades)} trades, {len(skipped)} overlaps/skips")


if __name__ == "__main__":
    main()
