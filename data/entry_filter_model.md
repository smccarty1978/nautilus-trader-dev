# Entry Filter Model — Reject Drifters

## Purpose

Train a new model specifically to filter out "drifter" trades at the 30s delay point. The existing exit model (should_hold, AUC 0.72) handles winners beautifully. The SL handles losers. The problem is the 42% of trades that do neither — they drift sideways and bleed.

## Data Source

`studies/regime_5s_ml/results/dynamic_exit_2025.parquet`

## Step 1: Build Training Dataset

For each trade, extract features at bar 6 (30s delay). Label based on what happened:

```python
for each trade_id:
    trade_bars = df[df['trade_id'] == tid].sort_values('bar_sequence')
    
    if len(trade_bars) <= 6:
        continue  # Trade died before 30s — auto-filtered
    
    delay_bar = trade_bars.iloc[6]  # Bar 6 = 30s
    features = delay_bar[feature_columns]  # All 30 in-trade features
    
    # Classify trade outcome using the SL+model system:
    # Replay from bar 6 forward:
    #   - Did forward_mae_atr >= 0.50? → SL exit
    #   - Did running_mfe_atr >= 0.75 AND model predicted exit? → Model exit
    #   - Neither? → Drifter
    
    # Simplified: use the simulation results from the previous analysis
    # We already know which trades were SL exits, model exits, or drifters
```

### Labels

```
resolves_cleanly    # PRIMARY TARGET
                    # 1 if trade hits SL OR reaches 0.75 MFE from delayed entry
                    # 0 if trade drifts to regime flip without hitting either
                    # The SL+model system produces +$14/trade net on "resolves" trades

reaches_075_mfe     # SECONDARY TARGET  
                    # 1 if trade reaches 0.75 ATR MFE from delayed entry
                    # 0 otherwise
                    # These are the trades where the exit model activates

profitable_trade    # TERTIARY TARGET
                    # 1 if trade would be net profitable under SL+model system
                    # (model exits at +$149 avg, some SL trades lose -$68)
```

### Expected Distribution (from previous results)

```
| Outcome | Count | Rate |
|---------|-------|------|
| Model exit (reached 0.75 MFE, model exited) | ~1,104 | ~24% |
| SL exit (hit -0.50 ATR) | ~1,501 | ~33% |
| Drifter (regime flip, no SL or model) | ~1,879 | ~42% |

resolves_cleanly = 1: ~58%
resolves_cleanly = 0: ~42%
```

## Step 2: Train Entry Filter Model

- **Train**: Jan-Sep 2025 (extract bar 6 from each trade, label as above)
- **Test**: Oct-Dec 2025
- **Features**: All 30 in-trade features at bar 6
- **Target**: `resolves_cleanly` (primary)
- **Model**: LightGBM

Report:
```
AUC train:
AUC test:
Feature importance top 15:
Calibration table:
```

Also train on `reaches_075_mfe` and `profitable_trade` for comparison.

## Step 3: Feature Importance

Which features at 30s predict drifters vs resolvers?

```
Top 10 features:
| Rank | Feature | Resolves Mean | Drifter Mean | Diff (std) |
|------|---------|---------------|-------------|------------|
```

Hypothesis: drifters show low `unrealized_pnl_atr` (barely moved), low `pnl_slope_6bar` (no momentum), low `volume_current_vs_avg` (no participation) at bar 6.

## Step 4: Combined System Simulation (Test Set Q4)

Use the NEW entry filter model at bar 6. If it passes, enter and use the EXISTING exit model for management.

```
Flow:
  Regime flip → wait 30s (6 bars) → Entry model evaluates
    → prob < entry_threshold: SKIP
    → prob >= entry_threshold: ENTER
      → SL at -0.50 ATR from delayed entry
      → Every 5s: existing exit model evaluates
      → After MFE >= 0.75 ATR: if exit model < 0.70 → take profit
      → Otherwise hold until SL or exit model triggers
      → If regime flips and no exit: EXIT at regime flip price
```

### Threshold Sweep

```
| Entry Thresh | Trades (Q4) | Trades/day | SL Exits | Model Exits | Drifters | Avg Gross $ | Avg Net $ | Total Net $ | PF |
|-------------|-------------|------------|----------|-------------|----------|-------------|-----------|-------------|-----|
| None (all)  |       4,484 |       49.8 |    1,501 |       1,104 |    1,879 |        +4.1 |      -5.9 |     -26,450 | ... |
| > 0.40      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.45      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.50      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.55      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.60      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.65      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.70      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.75      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
| > 0.80      |           ? |          ? |        ? |           ? |        ? |           ? |         ? |           ? |   ? |
```

**Key columns to watch:**
- Drifter count should drop faster than model exit count
- Avg gross $ should climb as drifters are filtered
- Trades/day in the 10-30 range is the sweet spot

### Breakdown by Exit Type at Best Threshold

```
| Exit Type | Count | Avg Gross $ | Avg Net $ | WR |
|-----------|-------|-------------|-----------|-----|
| Model exit | | | | |
| SL exit | | | | |
| Drifter (regime flip) | | | | |
| Total | | | | |
```

## Step 5: Retrain Entry Filter on Better Target (if needed)

If `resolves_cleanly` doesn't separate well, try training directly on:

```
net_profitable = 1 if trade PnL > $10 (covers friction)
               = 0 otherwise
```

This directly optimizes for what we want: trades that make money after friction.

## Step 6: The Money Line

Best combined system on Q4 test set:

```
| Metric | No Filter | Entry Filter + Exit Model |
|--------|-----------|--------------------------|
| Trades/day | 49.8 | ? |
| Avg gross $/trade | +4.1 | ? |
| Avg net $/trade | -5.9 | ? |
| Total net (Q4) | -$26,450 | ? |
| Annualized net | | ? |
| PF (net) | | ? |
| Months positive (3) | | ? |
| Drifter rate | 42% | ? |
```

## What Success Looks Like

- Drifter rate drops from 42% to <20%
- Trades/day: 15-30
- Avg net PnL: > $10/trade
- PF > 1.20 net
- Annualized: > $50K/contract

## Output

- Entry model: `studies/regime_5s_ml/results/entry_filter_model.pkl`
- Analysis: `studies/regime_5s_ml/results/entry_filter_analysis.md`
