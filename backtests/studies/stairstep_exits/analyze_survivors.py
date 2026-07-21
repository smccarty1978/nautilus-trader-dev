"""NQ Survivor and Position Add-On Expectancy Study - Analysis.

Loads parquet files, computes survivor milestone metrics, simulates 5 add-on rules
under 3 risk variants, answers the 7 critical questions, and outputs the report.
"""
from __future__ import annotations
import os, sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RES = Path("studies/stairstep_exits/results")
YEARS = (2021, 2022, 2023, 2024)
MULT = 20.0
TICK = 0.25
TICK_VAL = TICK * MULT          # $5 per tick
COMMISSION = 5.0                # $5 RT per contract
SLIPPAGE = 0.5                  # 0.5 tick exit slippage per contract
COST_PER_CONTRACT = COMMISSION + SLIPPAGE * TICK_VAL # $7.50

def pf(x):
    w = x[x > 0].sum()
    ls = -x[x < 0].sum()
    return (w / ls) if ls > 0 else np.inf

def max_dd(pnl_series):
    eq = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min()) if len(eq) else 0.0

def load_data():
    trades = []
    milestones = []
    adds = []
    for y in YEARS:
        t_path = RES / f"survivor_trades_{y}.parquet"
        m_path = RES / f"survivor_milestones_{y}.parquet"
        a_path = RES / f"survivor_adds_{y}.parquet"
        if t_path.exists():
            trades.append(pd.read_parquet(t_path))
        if m_path.exists():
            milestones.append(pd.read_parquet(m_path))
        if a_path.exists():
            adds.append(pd.read_parquet(a_path))
            
    df_trades = pd.concat(trades, ignore_index=True)
    df_milestones = pd.concat(milestones, ignore_index=True)
    df_adds = pd.concat(adds, ignore_index=True)
    
    # Sort trades chronologically
    df_trades = df_trades.sort_values("entry_ts").reset_index(drop=True)
    
    # Pre-calculate baseline net PnL (for 1 contract)
    df_trades["net_pnl_1c"] = (df_trades["exit_px"] - df_trades["entry_px"]) * df_trades["direction"] * MULT - COST_PER_CONTRACT
    
    return df_trades, df_milestones, df_adds

def analyze_population(pop, df_t, df_m, df_a):
    df_t = df_t[df_t.population == pop].copy()
    df_m = df_m[df_m.population == pop].copy()
    df_a = df_a[df_a.population == pop].copy()
    
    N_total = len(df_t)
    if N_total == 0:
        return None, None, None
        
    # 1. Compile Milestones Table
    m_joined = df_m.merge(df_t[["entry_id", "year", "atr_at_entry", "max_mfe_pts"]], on=["entry_id", "year"], how="left")
    
    m_rows = []
    for m_name in m_joined["milestone"].unique():
        sub = m_joined[m_joined.milestone == m_name]
        count = len(sub)
        pct_orig = count / N_total
        
        # Future EV ($) = remaining_pnl_pts * 20.0 - COST_PER_CONTRACT ($7.50)
        net_rem = sub["remaining_pnl_pts"] * MULT - COST_PER_CONTRACT
        future_ev = net_rem.mean()
        
        reach_2 = (sub["max_mfe_pts"] / sub["atr_at_entry"] >= 2.0).mean()
        reach_3 = (sub["max_mfe_pts"] / sub["atr_at_entry"] >= 3.0).mean()
        
        top_10 = sub["remaining_pnl_atr"].quantile(0.90)
        bot_10 = sub["remaining_pnl_atr"].quantile(0.10)
        
        m_rows.append({
            "Survivor State": m_name,
            "Count": count,
            "% Original": pct_orig,
            "Future EV ($)": future_ev,
            "Reach +2 ATR": reach_2,
            "Reach +3 ATR": reach_3,
            "Top 10%": top_10,
            "Bottom 10%": bot_10
        })
        
    df_m_res = pd.DataFrame(m_rows).sort_values("Future EV ($)", ascending=False).reset_index(drop=True)
    
    # Get best survivor state
    best_m_state = df_m_res.iloc[0]["Survivor State"] if len(df_m_res) > 0 else None
    
    # 2. Simulate Add-On Rules
    # Add rules mapping: Add A, B, C, D, E
    add_rules = {
        "Add A": ("Reached +0.50 ATR", "Reached +0.50 ATR"),
        "Add B": ("Reached +1.00 ATR", "Reached +1.00 ATR"),
        "Add C": ("Passed V2 prove-it gate", "Passed V2 prove-it gate"),
        "Add D": ("No opposing 5s flip first 90s", "No opposing 5s flip first 90s"),
        "Add E": (best_m_state, f"Best: {best_m_state}")
    }
    
    add_rows = []
    
    # We will simulate for all combinations of Add Rule and Variant
    for rule_name, (m_target, m_label) in add_rules.items():
        if m_target is None:
            continue
            
        for variant in (1, 2, 3):
            # Extract adds for this milestone and variant
            sub_adds = df_a[(df_a.milestone == m_target) & (df_a.variant == variant)]
            
            # Left join trades with sub_adds
            joined = df_t.merge(sub_adds[["entry_id", "year", "px_milestone", "exit_px", "add_pnl_pts"]], 
                               on=["entry_id", "year"], how="left", suffixes=("", "_add"))
            
            # Compute net combined PnL
            # For each trade:
            # If milestone is reached (px_milestone is not null):
            # - Original contract exits at:
            #   - Variant 1, 2: exit_px (baseline exit)
            #   - Variant 3: exit_px_add (average stop exit)
            # - Add-on contract exits at: exit_px_add
            # If milestone NOT reached:
            # - Original contract exits at exit_px (baseline exit), no add-on.
            
            orig_exit = np.where(joined["px_milestone"].isna(), joined["exit_px"], 
                                 np.where(variant == 3, joined["exit_px_add"], joined["exit_px"]))
            
            orig_net = (orig_exit - joined["entry_px"]) * joined["direction"] * MULT - COST_PER_CONTRACT
            
            add_net = np.where(joined["px_milestone"].isna(), 0.0,
                               (joined["exit_px_add"] - joined["px_milestone"]) * joined["direction"] * MULT - COST_PER_CONTRACT)
            
            combined_net = orig_net + add_net
            contracts = np.where(joined["px_milestone"].isna(), 1.0, 2.0)
            
            # Metrics
            total_net = combined_net.sum()
            net_per_tr = combined_net.mean()
            win_pct = (combined_net > 0).mean()
            pf_val = pf(combined_net.to_numpy())
            dd_val = max_dd(combined_net.to_numpy())
            avg_contracts = contracts.mean()
            
            # Append pooled results
            add_rows.append({
                "Add Rule": f"{rule_name} ({m_label}) - Var {variant}",
                "rule_name": rule_name,
                "variant": variant,
                "m_target": m_target,
                "Year": "Pooled",
                "Total Net $/Trade": net_per_tr,
                "Max DD": dd_val,
                "PF": pf_val,
                "Win %": win_pct,
                "Avg Contracts Traded": avg_contracts,
                "pnl_series": combined_net.to_numpy()
            })
            
            # Year-by-year breakdown
            for yr in YEARS:
                yr_mask = (joined.year == yr)
                yr_combined_net = combined_net[yr_mask]
                yr_contracts = contracts[yr_mask]
                
                if len(yr_combined_net) > 0:
                    add_rows.append({
                        "Add Rule": f"{rule_name} ({m_label}) - Var {variant}",
                        "rule_name": rule_name,
                        "variant": variant,
                        "m_target": m_target,
                        "Year": str(yr),
                        "Total Net $/Trade": yr_combined_net.mean(),
                        "Max DD": max_dd(yr_combined_net.to_numpy()),
                        "PF": pf(yr_combined_net.to_numpy()),
                        "Win %": (yr_combined_net > 0).mean(),
                        "Avg Contracts Traded": yr_contracts.mean(),
                        "pnl_series": yr_combined_net.to_numpy()
                    })
                    
    df_adds_res = pd.DataFrame(add_rows)
    return df_m_res, df_adds_res, best_m_state

def format_markdown_table(df, cols, align=None):
    if align is None:
        align = ["left"] + ["right"] * (len(cols) - 1)
        
    hdr = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" if a == "left" else "---:" for a in align) + " |"
    
    rows = []
    for _, r in df.iterrows():
        fmt_vals = []
        for k in cols:
            val = r[k]
            if isinstance(val, float):
                if k.startswith("%") or k in ("Win %", "Reach +2 ATR", "Reach +3 ATR"):
                    fmt_vals.append(f"{val:.1%}")
                elif k in ("Future EV ($)", "Total Net $/Trade", "Total Net PnL ($)"):
                    fmt_vals.append(f"{val:+.2f}")
                elif k in ("Max DD",):
                    fmt_vals.append(f"{val:,.0f}")
                elif k in ("PF", "Avg Contracts Traded"):
                    fmt_vals.append(f"{val:.2f}")
                elif k in ("Top 10%", "Bottom 10%"):
                    fmt_vals.append(f"{val:+.2f} ATR")
                else:
                    fmt_vals.append(f"{val:.2f}")
            elif isinstance(val, int) or isinstance(val, np.int64):
                if k in ("Count",):
                    fmt_vals.append(f"{val:,}")
                else:
                    fmt_vals.append(str(val))
            else:
                fmt_vals.append(str(val))
        rows.append("| " + " | ".join(fmt_vals) + " |")
        
    return "\n".join([hdr, sep] + rows)

def main():
    print("Loading replayed data...")
    df_t, df_m, df_a = load_data()
    print(f"Loaded {len(df_t):,} trade records, {len(df_m):,} milestone records, {len(df_a):,} add records.")
    
    # Process Population A and B
    print("Analyzing Population A (Raw Flips)...")
    df_m_a, df_adds_a, best_m_a = analyze_population("A", df_t, df_m, df_a)
    print("Analyzing Population B (Bar1 Confirmed)...")
    df_m_b, df_adds_b, best_m_b = analyze_population("B", df_t, df_m, df_a)
    
    # Generate report contents
    report = []
    report.append("# NQ Flip Survivor / Position Add-On Expectancy Study - Report")
    report.append("\n## Executive Summary\n")
    
    # We will answer the critical questions in the summary
    report.append("This study evaluates whether surviving trades from two regime flip entry populations can support profitable position additions (adds), even if the initial entries are net-negative.\n")
    report.append("The study is run across years 2021–2024 using high-fidelity 1s path replay. The baseline exit is `V0_regime` (exit on opposite 1m regime flip, with flip-bar-open catastrophic stop for raw flips).")
    report.append(f"We evaluated 14 survivor states and simulated 5 add-on rules (Add A-E) under 3 risk management variants with a strict transaction cost model ($5 RT commission + 0.5-tick exit slippage = $7.50 per contract).\n")
    
    # Best milestone stats
    report.append("### Key Findings:\n")
    report.append(f"- **Population A (Raw Flips):** Best survivor state is `{best_m_a}`. Its future forward expectancy is `{df_m_a.iloc[0]['Future EV ($)']:+.2f}`. out of `{df_m_a.iloc[0]['Count']:,}` survivors.")
    report.append(f"- **Population B (Bar1 Confirmed):** Best survivor state is `{best_m_b}`. Its future forward expectancy is `{df_m_b.iloc[0]['Future EV ($)']:+.2f}`. out of `{df_m_b.iloc[0]['Count']:,}` survivors.\n")
    
    # Let's check if ANY survivor state is profitable
    pos_m_a = df_m_a[df_m_a["Future EV ($)"] > 0]
    pos_m_b = df_m_b[df_m_b["Future EV ($)"] > 0]
    report.append(f"**Positive Forward Expectancy Survivor States:**")
    report.append(f"- Population A: {len(pos_m_a)} / {len(df_m_a)} states have positive forward expectancy.")
    report.append(f"- Population B: {len(pos_m_b)} / {len(df_m_b)} states have positive forward expectancy.\n")
    
    # Let's check if ANY add-on rule is profitable
    pooled_a = df_adds_a[df_adds_a.Year == "Pooled"].sort_values("Total Net $/Trade", ascending=False)
    pooled_b = df_adds_b[df_adds_b.Year == "Pooled"].sort_values("Total Net $/Trade", ascending=False)
    
    report.append(f"**Best Performing Add-on Rules (Pooled 2021-2024):**")
    report.append(f"- Population A: Top rule is `{pooled_a.iloc[0]['Add Rule']}` with Net/Trade = `{pooled_a.iloc[0]['Total Net $/Trade']:+.2f}` (Win% = {pooled_a.iloc[0]['Win %']:.1%}, PF = {pooled_a.iloc[0]['PF']:.2f}, Avg Contracts = {pooled_a.iloc[0]['Avg Contracts Traded']:.2f})")
    report.append(f"- Population B: Top rule is `{pooled_b.iloc[0]['Add Rule']}` with Net/Trade = `{pooled_b.iloc[0]['Total Net $/Trade']:+.2f}` (Win% = {pooled_b.iloc[0]['Win %']:.1%}, PF = {pooled_b.iloc[0]['PF']:.2f}, Avg Contracts = {pooled_b.iloc[0]['Avg Contracts Traded']:.2f})\n")
    
    # Compile Q&A section
    report.append("---")
    report.append("\n## Answers to Critical Questions\n")
    
    # Q1: Do any survivor states exhibit positive forward expectancy?
    q1_ans = "Yes" if (len(df_m_a[df_m_a["Future EV ($)"] + 7.50 > 0]) > 0 or len(df_m_b[df_m_b["Future EV ($)"] + 7.50 > 0]) > 0) else "No"
    report.append(f"#### Q1: Do any survivor states exhibit positive forward expectancy (gross of exit costs)?\n**Answer:** {q1_ans}. ")
    report.append("Let's look at the gross expectancy (Future EV + $7.50 exit costs):")
    for pop_lbl, df_m_p in [("Population A (Raw)", df_m_a), ("Population B (Bar1)", df_m_b)]:
        gross_pos = df_m_p[(df_m_p["Future EV ($)"] + 7.50) > 0]
        report.append(f"- {pop_lbl}: {len(gross_pos)} / {len(df_m_p)} states have positive gross forward expectancy.")
        if len(gross_pos) > 0:
            top_state = gross_pos.iloc[0]
            report.append(f"  - Top state: `{top_state['Survivor State']}` has gross EV of `{top_state['Future EV ($)'] + 7.50:+.2f}`.")
            
    # Q2: Do any survivor states exhibit positive forward expectancy after realistic costs?
    q2_ans = "Yes" if (len(pos_m_a) > 0 or len(pos_m_b) > 0) else "No"
    report.append(f"\n#### Q2: Do any survivor states exhibit positive forward expectancy after realistic costs?\n**Answer:** {q2_ans}. ")
    for pop_lbl, pos_m_p in [("Population A (Raw)", pos_m_a), ("Population B (Bar1)", pos_m_b)]:
        report.append(f"- {pop_lbl}: {len(pos_m_p)} states show positive net EV.")
        for _, r in pos_m_p.iterrows():
            report.append(f"  - `{r['Survivor State']}`: Net EV = `{r['Future EV ($)']:+.2f}`")
            
    # Q3: Is the add-on contract itself profitable?
    # To answer Q3, we must look at the add-on contract's own Net PnL (add_pnl_pts * 20.0 - 7.50) for the triggered trades
    report.append(f"\n#### Q3: Is the add-on contract itself profitable? (Not the original trade. The added contract.)\n**Answer:** ")
    for pop_lbl, pop_val, df_a_p in [("Population A (Raw)", "A", df_a), ("Population B (Bar1)", "B", df_a)]:
        report.append(f"\n**{pop_lbl}:**")
        df_a_p_pop = df_a_p[df_a_p.population == pop_val]
        # Calculate add-on net PnL
        df_a_p_pop = df_a_p_pop.copy()
        df_a_p_pop["net_add_pnl"] = df_a_p_pop["add_pnl_pts"] * MULT - COST_PER_CONTRACT
        
        # Group by milestone and variant
        add_stats = df_a_p_pop.groupby(["milestone", "variant"])["net_add_pnl"].mean().unstack()
        add_stats.columns = [f"Var {c}" for c in add_stats.columns]
        add_stats = add_stats.reset_index()
        report.append(format_markdown_table(add_stats, ["milestone", "Var 1", "Var 2", "Var 3"]))
        
    # Q4: Does the prove-it gate create a profitable add location?
    report.append(f"\n#### Q4: Does the prove-it gate create a profitable add location?\n**Answer:** ")
    for pop_val, pop_lbl in [("A", "Population A"), ("B", "Population B")]:
        sub_a = df_adds_a if pop_val == "A" else df_adds_b
        gate_adds = sub_a[(sub_a.rule_name == "Add C") & (sub_a.Year == "Pooled")]
        report.append(f"\n**{pop_lbl} (Add C - Passed V2 prove-it gate):**")
        report.append(format_markdown_table(gate_adds, ["Add Rule", "Total Net $/Trade", "PF", "Win %", "Avg Contracts Traded"]))
        
    # Q5: Does the "no opposing 5s flip for 90s" condition create a profitable add location?
    report.append(f"\n#### Q5: Does the 'no opposing 5s flip for 90s' condition create a profitable add location?\n**Answer:** ")
    for pop_val, pop_lbl in [("A", "Population A"), ("B", "Population B")]:
        sub_a = df_adds_a if pop_val == "A" else df_adds_b
        flip_adds = sub_a[(sub_a.rule_name == "Add D") & (sub_a.Year == "Pooled")]
        report.append(f"\n**{pop_lbl} (Add D - No opposing 5s flip first 90s):**")
        report.append(format_markdown_table(flip_adds, ["Add Rule", "Total Net $/Trade", "PF", "Win %", "Avg Contracts Traded"]))
        
    # Q6: Is Raw or Bar1 superior for a probe-and-add framework?
    report.append(f"\n#### Q6: Is Raw or Bar1 superior for a probe-and-add framework?\n**Answer:** ")
    # Compare baseline net/trade for raw vs bar1
    base_a = df_t[df_t.population == "A"]["net_pnl_1c"].mean()
    base_b = df_t[df_t.population == "B"]["net_pnl_1c"].mean()
    report.append(f"- Baseline 1-contract Net/Trade: Raw Flip = `{base_a:+.2f}`, Bar1 Confirmed = `{base_b:+.2f}`.")
    report.append(f"- Best Pooled Add-on Net/Trade: Raw Flip = `{pooled_a.iloc[0]['Total Net $/Trade']:+.2f}` (`{pooled_a.iloc[0]['Add Rule']}`), Bar1 Confirmed = `{pooled_b.iloc[0]['Total Net $/Trade']:+.2f}` (`{pooled_b.iloc[0]['Add Rule']}`).")
    
    # Q7: Can a 1-contract probe + conditional add outperform a fixed-size entry?
    report.append(f"\n#### Q7: Can a 1-contract probe + conditional add outperform a fixed-size entry?\n**Answer:** ")
    report.append("We compare the best probe-and-add rules to immediately entering 2 contracts (which is 2 * baseline 1-contract Net/Trade):\n")
    for pop_val, pop_lbl, base_val, df_adds_p in [("A", "Population A (Raw)", base_a, df_adds_a), ("B", "Population B (Bar1)", base_b, df_adds_b)]:
        fixed_2c = base_val * 2
        best_p_add = df_adds_p[(df_adds_p.Year == "Pooled")].sort_values("Total Net $/Trade", ascending=False).iloc[0]
        report.append(f"**{pop_lbl}:**")
        report.append(f"- Baseline 1-contract Net/Trade: `{base_val:+.2f}`")
        report.append(f"- Fixed 2-contract Net/Trade: `{fixed_2c:+.2f}`")
        report.append(f"- Best Probe-and-Add Net/Trade: `{best_p_add['Total Net $/Trade']:+.2f}` (`{best_p_add['Add Rule']}`)")
        if best_p_add['Total Net $/Trade'] > fixed_2c:
            report.append(f"  - **Outperforms:** The probe-and-add structure improves Net/Trade by `{best_p_add['Total Net $/Trade'] - fixed_2c:+.2f}` compared to fixed 2-contract size.")
        else:
            report.append(f"  - **Does NOT outperform:** Fixed size loses less (or makes more) than the probe-and-add structure.")
            
    # Compile Tables Section
    report.append("---")
    report.append("\n## Required Tables\n")
    
    report.append("### 1. Population A (Raw Flips) - Survivor States")
    m_cols = ["Survivor State", "Count", "% Original", "Future EV ($)", "Reach +2 ATR", "Reach +3 ATR", "Top 10%", "Bottom 10%"]
    report.append(format_markdown_table(df_m_a, m_cols))
    
    report.append("\n### 2. Population B (Bar1 Confirmed Flips) - Survivor States")
    report.append(format_markdown_table(df_m_b, m_cols))
    
    report.append("\n### 3. Population A (Raw Flips) - Add-On Simulation Results")
    add_cols = ["Add Rule", "Year", "Total Net $/Trade", "Max DD", "PF", "Win %", "Avg Contracts Traded"]
    # Separate pooled and yearly breakdown
    pooled_a_tbl = df_adds_a[df_adds_a.Year == "Pooled"].copy()
    report.append(format_markdown_table(pooled_a_tbl, add_cols))
    
    report.append("\n### 4. Population A (Raw Flips) - Yearly Breakdown of Top Add-On Rules")
    # Get top 3 add-on rules to show year-by-year
    top_rules_a = pooled_a.head(3)["Add Rule"].tolist()
    yearly_a = df_adds_a[df_adds_a["Add Rule"].isin(top_rules_a) & (df_adds_a.Year != "Pooled")].sort_values(["Add Rule", "Year"])
    report.append(format_markdown_table(yearly_a, ["Add Rule", "Year", "Total Net $/Trade", "Max DD", "PF", "Win %", "Avg Contracts Traded"]))
    
    report.append("\n### 5. Population B (Bar1 Confirmed Flips) - Add-On Simulation Results")
    pooled_b_tbl = df_adds_b[df_adds_b.Year == "Pooled"].copy()
    report.append(format_markdown_table(pooled_b_tbl, add_cols))
    
    report.append("\n### 6. Population B (Bar1 Confirmed Flips) - Yearly Breakdown of Top Add-On Rules")
    top_rules_b = pooled_b.head(3)["Add Rule"].tolist()
    yearly_b = df_adds_b[df_adds_b["Add Rule"].isin(top_rules_b) & (df_adds_b.Year != "Pooled")].sort_values(["Add Rule", "Year"])
    report.append(format_markdown_table(yearly_b, ["Add Rule", "Year", "Total Net $/Trade", "Max DD", "PF", "Win %", "Avg Contracts Traded"]))
    
    # Save report
    out_dir = RES
    out_dir.mkdir(parents=True, exist_ok=True)
    report_text = "\n".join(report)
    (out_dir / "survivor_study_report.md").write_text(report_text, encoding="utf-8")
    
    # Print a summary to stdout
    print("\n" + "="*40 + "\nSURVIVOR STUDY COMPLETED SUCCESSFULLY\n" + "="*40)
    print(f"Population A Top Milestone: {best_m_a} (Net EV: {df_m_a.iloc[0]['Future EV ($)']:+.2f})")
    print(f"Population B Top Milestone: {best_m_b} (Net EV: {df_m_b.iloc[0]['Future EV ($)']:+.2f})")
    print(f"Wrote report to {out_dir / 'survivor_study_report.md'}")

if __name__ == "__main__":
    main()
