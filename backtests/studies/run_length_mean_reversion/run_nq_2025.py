"""Run-Length Mean Reversion Study — NQ 2025 RTH+ETH.

Loads NQ 1m bars directly from the catalog (no 1s resample — same data,
faster, same roll exposure), derives RTH/ETH sessions in CT, drops bars
within +/- 3 days of quarterly contract rolls (3rd Thursday Mar/Jun/Sep/Dec),
runs causal + look-ahead studies, and writes Markdown + parquet + heatmaps.

Empirical confirmation that 1m bars have roll discontinuities:
  Sep 17 2025 19:00 CT close = 24341.50 (old contract)
  Sep 17 2025 19:01 CT open  = 24584.25 (new contract, +242.75 pt gap)
  Same pattern at all 4 quarterly rolls, hence the +/- 3 day filter.

Outputs:
    studies/run_length_mean_reversion/results_2025/
        report.md
        edge_maps_causal.parquet
        edge_maps_lookahead.parquet
        results_raw_causal.parquet
        results_raw_lookahead.parquet
        heatmaps/{entry_mode}_{stratum}_h{H}.png
"""

from __future__ import annotations

import os, sys
from dataclasses import asdict
from datetime import time as dt_time, date
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from studies.run_length_mean_reversion.run_length_study import (
    StudyConfig, run_study, edge_map_to_pivot,
)


CATALOG_PATH = "./data/catalog/NQ_2025"
BAR_TYPE = "NQ.XCME-1-MINUTE-LAST-EXTERNAL"
START = pd.Timestamp("2025-01-01", tz="UTC")
END = pd.Timestamp("2026-01-01", tz="UTC")
SPAN_LABEL = "2025"
OUT_DIR = Path(
    "studies/run_length_mean_reversion/results_2025")

ROLL_WINDOW_DAYS = 3  # +/- N CT days dropped around each quarterly roll


# ---------------- Roll-day filter ----------------

def quarterly_roll_dates(year: int) -> list[date]:
    """3rd Thursday of Mar/Jun/Sep/Dec for the given year (CT)."""
    rolls = []
    for month in (3, 6, 9, 12):
        # Find 3rd Thursday: weekday=3 (Mon=0)
        first = date(year, month, 1)
        offset = (3 - first.weekday()) % 7
        third_thursday = date(year, month,
                                  1 + offset + 14)
        rolls.append(third_thursday)
    return rolls


def filter_roll_window(bars: pd.DataFrame,
                            window_days: int) -> tuple[pd.DataFrame, int]:
    """Drop bars within +/- window_days CT of any quarterly roll. Returns
    (filtered_bars, dropped_count).
    """
    if window_days <= 0:
        return bars, 0
    years = sorted(set(bars["year"].values))
    drop_dates: set[date] = set()
    for yr in years:
        for rd in quarterly_roll_dates(int(yr)):
            for delta in range(-window_days, window_days + 1):
                drop_dates.add(rd + pd.Timedelta(days=delta).to_pytimedelta())
    ct_dates = bars["ts_ct"].dt.date
    keep_mask = ~ct_dates.isin(drop_dates)
    dropped = int((~keep_mask).sum())
    return bars[keep_mask].copy(), dropped


# ---------------- Data loading ----------------

def load_1m_bars(catalog_path: str, bar_type: str,
                    start: pd.Timestamp,
                    end: pd.Timestamp) -> pd.DataFrame:
    """Load 1m bars from NT catalog, indexed by close time (UTC).

    NT bar timestamp convention (after ts_init_delta is applied at catalog
    build): b.ts_event = OPEN time, b.ts_init = CLOSE time.
    """
    from nautilus_trader.persistence.catalog import (
        ParquetDataCatalog,
    )
    from nautilus_trader.model.data import BarType

    cat = ParquetDataCatalog(catalog_path)
    bar_type_obj = BarType.from_str(bar_type)
    bars = cat.bars(bar_types=[bar_type_obj],
                       start=start.value, end=end.value)
    if not bars:
        raise RuntimeError(
            f"No bars found for {bar_type} in {catalog_path}")
    df = pd.DataFrame([{
        "ts_close": int(b.ts_init),
        "open": float(b.open),
        "high": float(b.high),
        "low": float(b.low),
        "close": float(b.close),
        "volume": float(b.volume),
    } for b in bars])
    df["ts_close"] = pd.to_datetime(
        df["ts_close"], unit="ns", utc=True)
    df = df.set_index("ts_close").sort_index()
    return df


# ---------------- Session annotation ----------------

def annotate_sessions_ct(bars: pd.DataFrame) -> pd.DataFrame:
    """Add ts_ct, session ('RTH'/'ETH'), session_id, year columns.
    RTH = weekdays 08:30:00-14:59:59.999 CT.
    ETH session_id rolls at 17:00 CT (anchored to next CT calendar date).
    """
    out = bars.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    ts_ct = out.index.tz_convert("America/Chicago")

    rth_start = dt_time(8, 30, 0)
    rth_end = dt_time(15, 0, 0)

    times = ts_ct.time
    weekday = ts_ct.weekday
    is_weekday = weekday < 5
    is_rth = is_weekday & (times >= rth_start) & (times < rth_end)
    session = np.where(is_rth, "RTH", "ETH")

    eth_anchor = ts_ct.normalize()
    eth_anchor = np.where(
        ts_ct.hour >= 17,
        eth_anchor + pd.Timedelta(days=1),
        eth_anchor)
    eth_anchor = pd.DatetimeIndex(eth_anchor)
    rth_date = ts_ct.normalize()

    session_id = np.where(
        is_rth,
        rth_date.strftime("%Y-%m-%d") + "_RTH",
        eth_anchor.strftime("%Y-%m-%d") + "_ETH")

    out["ts_ct"] = ts_ct
    out["session"] = session
    out["session_id"] = session_id
    out["year"] = ts_ct.year
    return out


# ---------------- Heatmap ----------------

def render_heatmap(edge_map: pd.DataFrame, title: str,
                       out_path: Path,
                       baseline: float | None = None,
                       min_samples: int = 100) -> None:
    pivot_hit = edge_map_to_pivot(edge_map, "hit_rate")
    pivot_ret = edge_map_to_pivot(edge_map, "mean_ret_atr")
    pivot_n = edge_map_to_pivot(
        edge_map, "n").fillna(0).astype(int)
    mask = pivot_n < min_samples

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    center = baseline if baseline is not None else 0.5
    span = max(0.15, abs(
        pivot_hit.fillna(center).values - center).max())
    norm_hit = mcolors.TwoSlopeNorm(
        vmin=center - span, vcenter=center, vmax=center + span)
    hit_display = pivot_hit.where(~mask)
    im0 = axes[0].imshow(hit_display.values, cmap="RdBu_r",
                                norm=norm_hit, aspect="auto")
    axes[0].set_xticks(range(len(pivot_hit.columns)))
    axes[0].set_xticklabels(pivot_hit.columns,
                                   rotation=45, ha="right")
    axes[0].set_yticks(range(len(pivot_hit.index)))
    axes[0].set_yticklabels(pivot_hit.index)
    axes[0].set_xlabel("Magnitude (ATR units)")
    axes[0].set_ylabel("Run length")
    axes[0].set_title(f"Hit rate (baseline={center:.3f})")
    plt.colorbar(im0, ax=axes[0])
    for i in range(pivot_hit.shape[0]):
        for j in range(pivot_hit.shape[1]):
            v = pivot_hit.values[i, j]
            n = pivot_n.values[i, j]
            if pd.isna(v): continue
            color = ("white" if abs(v - center) > span * 0.5
                       else "black")
            label = (f"{v:.2f}\nn={n}" if not mask.values[i, j]
                       else f"({v:.2f})\nn={n}")
            axes[0].text(j, i, label, ha="center",
                            va="center", color=color, fontsize=8)

    ret_display = pivot_ret.where(~mask)
    ret_arr = ret_display.values
    if np.isnan(ret_arr).all():
        ret_span = 0.1
    else:
        ret_span = max(0.1, np.nanmax(np.abs(ret_arr)))
    norm_ret = mcolors.TwoSlopeNorm(
        vmin=-ret_span, vcenter=0, vmax=ret_span)
    im1 = axes[1].imshow(ret_arr, cmap="RdBu_r",
                                norm=norm_ret, aspect="auto")
    axes[1].set_xticks(range(len(pivot_ret.columns)))
    axes[1].set_xticklabels(pivot_ret.columns,
                                   rotation=45, ha="right")
    axes[1].set_yticks(range(len(pivot_ret.index)))
    axes[1].set_yticklabels(pivot_ret.index)
    axes[1].set_xlabel("Magnitude (ATR units)")
    axes[1].set_ylabel("Run length")
    axes[1].set_title("Mean forward return (ATR units)")
    plt.colorbar(im1, ax=axes[1])
    for i in range(pivot_ret.shape[0]):
        for j in range(pivot_ret.shape[1]):
            v = pivot_ret.values[i, j]
            if pd.isna(v): continue
            color = ("white" if abs(v) > ret_span * 0.5
                       else "black")
            axes[1].text(j, i, f"{v:.2f}", ha="center",
                            va="center", color=color, fontsize=8)

    fig.suptitle(title, fontsize=12, fontweight="bold")
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


# ---------------- Markdown report ----------------

def edge_map_to_md(edge_map: pd.DataFrame, value_col: str,
                          fmt: str = "{:.3f}") -> str:
    pivot = edge_map_to_pivot(edge_map, value_col)
    n_pivot = edge_map_to_pivot(
        edge_map, "n").fillna(0).astype(int)
    cols = list(pivot.columns)
    header = "| run_len | " + " | ".join(
        str(c) for c in cols) + " |"
    sep = "|" + "|".join(["---"] * (len(cols) + 1)) + "|"
    lines = [header, sep]
    for idx in pivot.index:
        row = [str(idx)]
        for c in cols:
            v = pivot.loc[idx, c]
            n = (n_pivot.loc[idx, c]
                   if c in n_pivot.columns else 0)
            if pd.isna(v):
                row.append("—")
            else:
                row.append(f"{fmt.format(v)} (n={n})")
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def write_report(out_dir: Path, causal: dict, lookahead: dict,
                       bar_count: int, dropped_roll: int,
                       cfg: StudyConfig) -> Path:
    p = out_dir / "report.md"
    out_dir.mkdir(parents=True, exist_ok=True)
    L = []
    L.append("# Run-Length Mean Reversion Study — NQ 2025\n")
    L.append(f"**Span:** {SPAN_LABEL}  ")
    L.append(f"**Bar type:** `{BAR_TYPE}`  ")
    L.append(f"**Bars analyzed (after roll filter):** "
              f"{bar_count:,}  ")
    L.append(f"**Bars dropped by roll filter "
              f"(+/-{ROLL_WINDOW_DAYS}d around quarterly rolls):** "
              f"{dropped_roll:,}  ")
    L.append(f"**Causal-entry runs:** "
              f"{causal['n_runs']:,}  ")
    L.append(f"**Look-ahead-entry runs:** "
              f"{lookahead['n_runs']:,}\n")

    L.append("## Configuration\n")
    L.append("```")
    for k, v in asdict(cfg).items():
        L.append(f"{k}: {v}")
    L.append("```\n")

    L.append("## Method notes\n")
    L.append(
        f"- Bar direction: sign(close - prev_close). Doji bars (Δ=0) "
        f"terminate runs, do not start new ones.\n"
        f"- Run magnitude = |close[end] − open[start]|, normalized by "
        f"ATR(14, Wilder) sampled at the bar **before** run start.\n"
        f"- Causal entry: open of (run_end_idx + 2). Waits for the "
        f"reversal-confirming bar to close. Deployable.\n"
        f"- Look-ahead entry: open of (run_end_idx + 1). 1-bar look-ahead, "
        f"reported only as a sanity check.\n"
        f"- Forward returns signed so positive = mean-reversion paid "
        f"(short after up-runs, long after down-runs).\n"
        f"- Runs spanning a session boundary (RTH ↔ ETH) are dropped.\n"
        f"- Endpoints whose longest-horizon ({max(cfg.horizons)}-bar) "
        f"trade window crosses a session boundary are dropped uniformly "
        f"across all horizons (sample set identical at h=1 and "
        f"h={max(cfg.horizons)} within a stratum).\n"
        f"- **Roll filter**: bars within +/-{ROLL_WINDOW_DAYS} CT days "
        f"of each quarterly roll (3rd Thu Mar/Jun/Sep/Dec) are dropped. "
        f"Empirically, 1m bars at ~19:01 CT on roll-day eve show "
        f"200-235 pt gaps (catalog continuous-contract rolls). Without "
        f"this filter, those gap bars dominate the high-magnitude "
        f"mean-reversion buckets.\n"
        f"- Cells with n < {cfg.min_samples_for_display} samples are "
        f"flagged unreliable in heatmaps."
    )
    L.append("")

    L.append("## Unconditional baselines\n")
    L.append("**Global (RTH + ETH combined):**\n")
    L.append("| Horizon | Causal | Look-ahead |")
    L.append("|---|---|---|")
    for h in cfg.horizons:
        cb = causal["baselines"].get(h, np.nan)
        lb = lookahead["baselines"].get(h, np.nan)
        L.append(f"| {h} | {cb:.4f} | {lb:.4f} |")
    L.append("")

    causal_strata = causal.get("stratified_baselines") or {}
    look_strata = lookahead.get("stratified_baselines") or {}
    all_strata = sorted(set(causal_strata) | set(look_strata))
    for stratum in all_strata:
        L.append(f"**{stratum}:**\n")
        L.append("| Horizon | Causal | Look-ahead |")
        L.append("|---|---|---|")
        for h in cfg.horizons:
            cb = causal_strata.get(stratum, {}).get(h, np.nan)
            lb = look_strata.get(stratum, {}).get(h, np.nan)
            L.append(f"| {h} | {cb:.4f} | {lb:.4f} |")
        L.append("")

    for entry_mode, study in [
            ("Causal entry", causal),
            ("Look-ahead entry", lookahead)]:
        L.append(f"## {entry_mode}\n")
        strata = (study.get("stratified_edge_maps")
                     or {"ALL": study["edge_maps"]})
        for stratum, maps in strata.items():
            L.append(f"### Stratum: {stratum}\n")
            for h in cfg.horizons:
                em = maps[h]
                if em.empty:
                    L.append(f"#### Horizon {h}: no data\n")
                    continue
                L.append(f"#### Horizon {h} bars\n")
                L.append("**Hit rate (mean-reversion paid):**\n")
                L.append(edge_map_to_md(em, "hit_rate", "{:.3f}"))
                L.append("\n**Mean forward return (ATR):**\n")
                L.append(edge_map_to_md(
                    em, "mean_ret_atr", "{:+.3f}"))
                L.append("\n**Mean MFE (ATR):**\n")
                L.append(edge_map_to_md(
                    em, "mean_mfe", "{:+.3f}"))
                L.append("\n**Mean MAE (ATR):**\n")
                L.append(edge_map_to_md(
                    em, "mean_mae", "{:+.3f}"))
                L.append("")

    L.append("## Heatmaps\n")
    L.append("See `heatmaps/`. Naming: "
              "`{entry_mode}_{stratum}_h{H}.png`\n")

    L.append("## Caveats\n")
    L.append(
        "- No transaction costs applied. Net of ~1 tick of friction on "
        "NQ ($5/contract round-trip), edges below ~0.05 ATR are unlikely "
        "tradeable.\n"
        "- Single calendar year (2025). Out-of-sample validation needed "
        "before trusting any cell.\n"
        "- Bucket boundaries are arbitrary. Re-run with finer buckets "
        "to expose sub-structure.\n"
        "- Doji bars (close==prev_close) reset the run counter. Rare on "
        "1m NQ but non-zero in illiquid hours.\n"
        f"- Roll filter is a +/-{ROLL_WINDOW_DAYS} day calendar buffer, "
        f"not a tick-level surgical cut. Conservative; trades sample "
        f"size for safety.\n"
    )

    p.write_text("\n".join(L), encoding="utf-8")
    return p


# ---------------- Main ----------------

def main() -> int:
    print("=" * 70)
    print("Run-Length Mean Reversion — NQ 2025 (1m direct)")
    print("=" * 70)

    print(f"\n[1/5] Loading 1m bars from {CATALOG_PATH}...")
    bars = load_1m_bars(CATALOG_PATH, BAR_TYPE, START, END)
    print(f"  loaded {len(bars):,} 1m bars "
          f"[{bars.index[0]} .. {bars.index[-1]}]")

    print(f"\n[2/5] Annotating CT sessions...")
    bars = annotate_sessions_ct(bars)
    print(f"  RTH bars: {(bars['session']=='RTH').sum():,}")
    print(f"  ETH bars: {(bars['session']=='ETH').sum():,}")

    print(f"\n[3/5] Filtering +/-{ROLL_WINDOW_DAYS}d around "
          f"quarterly rolls...")
    bars, dropped = filter_roll_window(bars, ROLL_WINDOW_DAYS)
    print(f"  dropped {dropped:,} bars from roll windows")
    print(f"  remaining: {len(bars):,} bars")

    cfg_causal = StudyConfig(
        causal_entry=True, stratify_col="session",
        drop_runs_spanning_session=True,
        drop_horizon_crossing_session=True)
    cfg_lookahead = StudyConfig(
        causal_entry=False, stratify_col="session",
        drop_runs_spanning_session=True,
        drop_horizon_crossing_session=True)

    print(f"\n[4/5] Running causal-entry study...")
    causal = run_study(bars, cfg_causal)
    print(f"  -> {causal['n_runs']:,} runs analyzed")
    print(f"\n      Running look-ahead study (sanity check)...")
    lookahead = run_study(bars, cfg_lookahead)
    print(f"  -> {lookahead['n_runs']:,} runs analyzed")

    print(f"\n[5/5] Writing artifacts to {OUT_DIR}...")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    causal["results"].to_parquet(
        OUT_DIR / "results_raw_causal.parquet", index=False)
    lookahead["results"].to_parquet(
        OUT_DIR / "results_raw_lookahead.parquet", index=False)

    def edge_to_long(study, mode):
        rows = []
        strata = (study.get("stratified_edge_maps")
                     or {"ALL": study["edge_maps"]})
        for stratum, maps in strata.items():
            for h, em in maps.items():
                if em.empty: continue
                df = em.copy()
                df["stratum"] = stratum
                df["horizon"] = h
                df["entry_mode"] = mode
                rows.append(df)
        return (pd.concat(rows, ignore_index=True)
                  if rows else pd.DataFrame())

    edge_to_long(causal, "causal").to_parquet(
        OUT_DIR / "edge_maps_causal.parquet", index=False)
    edge_to_long(lookahead, "lookahead").to_parquet(
        OUT_DIR / "edge_maps_lookahead.parquet", index=False)

    heatmap_dir = OUT_DIR / "heatmaps"
    for entry_mode, study in [
            ("causal", causal), ("lookahead", lookahead)]:
        strata = (study.get("stratified_edge_maps")
                     or {"ALL": study["edge_maps"]})
        for stratum, maps in strata.items():
            for h in cfg_causal.horizons:
                em = maps[h]
                if em.empty: continue
                title = (f"{entry_mode.upper()} entry — "
                          f"{stratum} — horizon {h}")
                strat_bl = ((study.get("stratified_baselines")
                                or {}).get(stratum, {}))
                baseline = strat_bl.get(
                    h, study["baselines"].get(h))
                render_heatmap(
                    em, title,
                    heatmap_dir / f"{entry_mode}_{stratum}_h{h}.png",
                    baseline=baseline,
                    min_samples=cfg_causal.min_samples_for_display)

    rp = write_report(OUT_DIR, causal, lookahead,
                            bar_count=len(bars),
                            dropped_roll=dropped, cfg=cfg_causal)
    print(f"  Report: {rp}")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
