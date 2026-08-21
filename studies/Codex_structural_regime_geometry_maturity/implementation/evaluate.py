"""Attach accepted Walk-A labels to frozen OOS first crossings and aggregate."""
from __future__ import annotations
from pathlib import Path
import polars as pl
from studies.p90_regime_age_progress_diagnostic.implementation import outcomes as O
from studies.Codex_structural_regime_geometry_maturity.implementation.sealed_outcomes import load_engines, load_regime_ends

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'studies/Codex_structural_regime_geometry_maturity/results'

def main():
    x=pl.read_parquet(OUT/'oos_first_crossings.parquet').with_columns(
        trade_direction=pl.when(pl.col('direction')=='LONG').then(1).otherwise(-1))
    events=x.select('regime_id','checkpoint_decision_ns',pl.col('trade_direction').alias('direction'),
                    'checkpoint_reference_price','atr_at_checkpoint').unique(['regime_id','checkpoint_decision_ns','direction'])
    market,regimes=load_engines(); ends=load_regime_ends()
    sim=O.simulate(events,market,regimes,ends,progress_every=1000)
    y=x.join(sim,on=['regime_id','checkpoint_decision_ns'],how='left').with_columns(
        confirmed=pl.col('confirmed').fill_null(False))
    # The manifest's arm table is self-contained: causal score/features and
    # inherited Walk-A labels travel together, never in a sidecar only.
    y.write_parquet(OUT/'oos_first_crossings.parquet')
    y.write_parquet(OUT/'oos_crossing_events.parquet')
    group=['model_set','direction','maturity_bucket','threshold_quantile','threshold']
    metrics=(y.group_by(group).agg(n=pl.len(),p_flip_le_300s=pl.col('label').mean(),
        p_confirm_before_1atr=pl.col('confirmed').mean(),
        median_seconds_to_confirm=pl.col('seconds_to_confirm').filter(pl.col('confirmed')).median(),
        median_mae_to_confirm_atr=pl.col('mae_to_confirm_atr').filter(pl.col('confirmed')).median(),
        median_return_at_confirm_atr=pl.col('return_at_confirm_atr').filter(pl.col('confirmed')).median(),
        median_eventual_opposite_mfe_atr=pl.col('eventual_max_mfe_atr').filter(pl.col('confirmed')).median(),
        p_opposite_mfe_ge_1=pl.col('mfe_ge_1_0').filter(pl.col('confirmed')).mean(),
        p_opposite_mfe_ge_2=pl.col('mfe_ge_2_0').filter(pl.col('confirmed')).mean(),
        p_opposite_mfe_ge_3=pl.col('mfe_ge_3_0').filter(pl.col('confirmed')).mean()).sort(group))
    metrics.write_csv(OUT/'oos_crossing_metrics.csv')
    print({'crossings':y.height,'metric_rows':metrics.height})
if __name__=='__main__': main()
