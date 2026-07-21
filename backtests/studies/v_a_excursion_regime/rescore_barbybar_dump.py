"""Bar-by-bar rescore decision dump for the 1,298 matched no-flip
trades where the LIVE strategy exited LATER than the schedule.

For each in-trade minute, reconstruct both rescore decisions:
  - LIVE   : hold iff candidate exists AND frozen-model score >= 0.077
  - SCHED  : hold iff candidate exists AND walk-forward score >= 0.077

Both use the same eligibility (candidate present in the augmented
table) and the same 0.077 threshold. The matcher proved the live
feature/entry path reproduces the offline candidate table to the
penny, so scoring the augmented candidates with the frozen model
faithfully reproduces the live rescore decision.

Cross-check: reconstructed frozen score at the live exit bar should
match the strategy-recorded exit_score.

Output: per-(trade,minute) dump + a summary classifying WHY live held
when schedule exited.
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import lightgbm as lgb

NS = 1_000_000_000
RESCORE_THR = 0.0770
OUT = Path("studies/v_a_excursion_regime/results_v0")
FROZEN = OUT / "frozen_t1"
CANDS = OUT / "pre_flip_candidates_augmented.parquet"
OOS = OUT / "pre_flip_T1_n20_oos.parquet"
MATCHED = OUT / "noflip_matched_diff.parquet"
ONE_S = {2024: "data/raw/NQ_v0_1s_2024.parquet",
            2025: "data/raw/NQ_v0_1s_2025.parquet"}


def main():
    # --- frozen model + features ---
    model = lgb.Booster(model_file=str(FROZEN / "model.txt"))
    feats = json.loads((FROZEN / "feature_list.json").read_text())

    # --- score every augmented candidate with the frozen model ---
    cand = pd.read_parquet(CANDS)
    cand["frozen_score"] = model.predict(cand[feats])
    frozen_lk = {}
    for ts, d, s in zip(cand["close_ts_ns"],
                              cand["candidate_direction"],
                              cand["frozen_score"]):
        frozen_lk[(int(ts), int(d))] = float(s)
    print(f"Frozen-scored {len(frozen_lk):,} candidates")

    # --- walk-forward OOS scores ---
    oos = pd.read_parquet(OOS)
    wf_lk = {}
    for ts, d, s in zip(oos["close_ts_ns"], oos["direction"],
                              oos["p_score"]):
        wf_lk[(int(ts), int(d))] = float(s)
    print(f"Walk-forward OOS scores: {len(wf_lk):,}")

    # --- matched no-flip trades, live-exited-later subset ---
    m = pd.read_parquet(MATCHED)
    later = m[m["l_exit_ts"] > m["s_exit_ts"]].copy().reset_index(
        drop=True)
    print(f"Live-exited-later matched no-flip trades: {len(later):,}")

    # --- 1s bars for unrealized PnL ---
    bars = {}
    for y, p in ONE_S.items():
        b = pd.read_parquet(p, columns=["open"])
        b.index = pd.to_datetime(b.index, utc=True)
        b = b.sort_index()
        bars[y] = (b.index.view("int64"), b["open"].to_numpy())

    def bar_open_at(ts):
        for y in (2024, 2025):
            ts_arr, o = bars[y]
            i = np.searchsorted(ts_arr, ts, side="right")
            if 0 < i <= len(ts_arr):
                # ensure within this year's range
                if ts_arr[0] <= ts <= ts_arr[-1] + NS:
                    return float(o[min(i, len(o) - 1)])
        return np.nan

    rows = []
    for tr_id, r in later.iterrows():
        entry_ts = int(r["entry_ts"])
        d = int(r["direction"])
        entry_px = float(r["l_entry_px"])
        l_exit = int(r["l_exit_ts"])
        s_exit = int(r["s_exit_ts"])
        horizon = max(l_exit, s_exit)
        offset = 60
        while True:
            check_ts = entry_ts + offset * NS
            if check_ts > horizon:
                break
            fz = frozen_lk.get((check_ts, d), None)
            wf = wf_lk.get((check_ts, d), None)
            live_elig = fz is not None
            sch_elig = wf is not None
            live_hold = live_elig and fz >= RESCORE_THR
            sch_hold = sch_elig and wf >= RESCORE_THR
            cur_px = bar_open_at(check_ts)
            unreal = ((cur_px - entry_px) * d * 20.0
                          if not np.isnan(cur_px) else np.nan)
            rows.append({
                "trade_id": tr_id,
                "entry_ts": entry_ts,
                "direction": d,
                "minute_offset": offset,
                "live_eligible": live_elig,
                "sched_eligible": sch_elig,
                "live_frozen_score": fz,
                "sched_wf_score": wf,
                "live_thr": RESCORE_THR,
                "sched_thr": RESCORE_THR,
                "live_decision": "hold" if live_hold else "exit",
                "sched_decision": "hold" if sch_hold else "exit",
                "unreal_pnl": unreal,
                "live_exit_ts": l_exit,
                "sched_exit_ts": s_exit,
            })
            offset += 60
    dump = pd.DataFrame(rows)
    dump.to_parquet(OUT / "rescore_barbybar_dump.parquet",
                       index=False)
    print(f"\nDump rows: {len(dump):,}  "
          f"({len(later):,} trades)")

    # ================= SUMMARY =================
    print(f"\n{'='*74}")
    print(f"WHY DOES LIVE HOLD WHEN SCHEDULE EXITS?")
    print(f"{'='*74}")
    # Decision points where schedule says EXIT but live says HOLD
    divg = dump[(dump["sched_decision"] == "exit")
                    & (dump["live_decision"] == "hold")]
    print(f"  Decision points sched=EXIT, live=HOLD: {len(divg):,}")
    if len(divg):
        # Classify the cause
        elig_mismatch = divg[~divg["sched_eligible"]
                                  & divg["live_eligible"]]
        score_mismatch = divg[divg["sched_eligible"]
                                   & divg["live_eligible"]]
        print(f"    eligibility mismatch "
              f"(sched no candidate, live has): "
              f"{len(elig_mismatch):,} "
              f"({len(elig_mismatch)/len(divg):.1%})")
        print(f"    score mismatch "
              f"(both eligible, sched wf<thr, live frozen>=thr): "
              f"{len(score_mismatch):,} "
              f"({len(score_mismatch)/len(divg):.1%})")
        if len(score_mismatch):
            print(f"\n  On score-mismatch points:")
            print(f"    sched walk-forward score: "
                  f"mean {score_mismatch['sched_wf_score'].mean():.4f}  "
                  f"median {score_mismatch['sched_wf_score'].median():.4f}")
            print(f"    live frozen score:        "
                  f"mean {score_mismatch['live_frozen_score'].mean():.4f}  "
                  f"median {score_mismatch['live_frozen_score'].median():.4f}")
            gap = (score_mismatch["live_frozen_score"]
                       - score_mismatch["sched_wf_score"])
            print(f"    frozen - walkforward gap: "
                  f"mean {gap.mean():+.4f}  median {gap.median():+.4f}")

    # Reverse: sched HOLD, live EXIT
    rev = dump[(dump["sched_decision"] == "hold")
                   & (dump["live_decision"] == "exit")]
    print(f"\n  Decision points sched=HOLD, live=EXIT: {len(rev):,}")

    # Agreement
    agree = dump[dump["sched_decision"] == dump["live_decision"]]
    print(f"  Decision points agree: {len(agree):,} "
          f"({len(agree)/len(dump):.1%})")

    # Eligibility-only stats
    print(f"\n  Eligibility flags across all decision points:")
    print(f"    live eligible:  {dump['live_eligible'].mean():.1%}")
    print(f"    sched eligible: {dump['sched_eligible'].mean():.1%}")
    elig_disagree = dump[dump["live_eligible"]
                              != dump["sched_eligible"]]
    print(f"    eligibility DISAGREE: {len(elig_disagree):,} "
          f"({len(elig_disagree)/len(dump):.1%})")
    if len(elig_disagree):
        live_only_e = elig_disagree[elig_disagree["live_eligible"]]
        sch_only_e = elig_disagree[elig_disagree["sched_eligible"]]
        print(f"      live-eligible only:  {len(live_only_e):,}")
        print(f"      sched-eligible only: {len(sch_only_e):,}")

    # Score distributions where BOTH eligible
    both = dump[dump["live_eligible"] & dump["sched_eligible"]]
    print(f"\n  Where BOTH eligible (n={len(both):,}):")
    print(f"    frozen score:       mean "
          f"{both['live_frozen_score'].mean():.4f}  "
          f"median {both['live_frozen_score'].median():.4f}")
    print(f"    walk-forward score: mean "
          f"{both['sched_wf_score'].mean():.4f}  "
          f"median {both['sched_wf_score'].median():.4f}")
    print(f"    frozen >= 0.077: {(both['live_frozen_score']>=RESCORE_THR).mean():.1%}")
    print(f"    wf >= 0.077:     {(both['sched_wf_score']>=RESCORE_THR).mean():.1%}")

    # Sample dump — first 3 trades, all minutes
    print(f"\n{'='*74}")
    print(f"SAMPLE — first 3 trades, bar-by-bar")
    print(f"{'='*74}")
    for tid in dump["trade_id"].unique()[:3]:
        t = dump[dump["trade_id"] == tid]
        r0 = t.iloc[0]
        l_off = (int(r0['live_exit_ts']) - int(r0['entry_ts'])) // NS
        s_off = (int(r0['sched_exit_ts']) - int(r0['entry_ts'])) // NS
        print(f"\n  trade {tid}  dir={int(r0['direction']):+d}  "
              f"live_exit=+{l_off}s  sched_exit=+{s_off}s")
        print(f"    {'min':>4} {'L-elig':>7} {'S-elig':>7} "
              f"{'frozen':>8} {'wf':>8} {'L-dec':>6} {'S-dec':>6} "
              f"{'unrealPnL':>10}")
        for _, rr in t.iterrows():
            fz = (f"{rr['live_frozen_score']:.4f}"
                     if rr['live_frozen_score'] is not None else "  --  ")
            wf = (f"{rr['sched_wf_score']:.4f}"
                     if rr['sched_wf_score'] is not None else "  --  ")
            up = (f"{rr['unreal_pnl']:+.0f}"
                     if not pd.isna(rr['unreal_pnl']) else "  --  ")
            print(f"    {int(rr['minute_offset']):>4} "
                  f"{str(rr['live_eligible']):>7} "
                  f"{str(rr['sched_eligible']):>7} "
                  f"{fz:>8} {wf:>8} "
                  f"{rr['live_decision']:>6} {rr['sched_decision']:>6} "
                  f"{up:>10}")

    print(f"\nSaved rescore_barbybar_dump.parquet")


if __name__ == "__main__":
    main()
