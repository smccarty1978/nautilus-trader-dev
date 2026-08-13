# post_confirm_retracement_recovery

Descriptive study of what happens **after** a confirmed fade trade reaches an MFE
rung and then gives part of it back. Asks whether "retraced D ATR and failed to
recover Y% within T seconds" is a state worth exiting on.

No model is trained here. No estimator library may be imported into
`implementation/` — gate V3 enforces that.

## How to run

```bash
# everything, ~1m45s end to end
python -m studies.post_confirm_retracement_recovery.run_study --stage all

# or one stage at a time; each is resumable and reads the previous stage's parquet
python -m studies.post_confirm_retracement_recovery.run_study --stage build
python -m studies.post_confirm_retracement_recovery.run_study --stage validate
```

| Stage | Seconds | Writes |
|---|---:|---|
| `build` | 23 | `arm_panel.parquet`, `recovery_state_panel.parquet`, `lineage_reconciliation.json` |
| `descriptive` | 2 | Phases 1, 3, 4, 5, 10 tables |
| `economics` | 11 | Phases 8, 9, 11 tables |
| `diagnostics` | 61 | Phases 12, 13, 14 tables |
| `validate` | 6 | `validation_report.json` |
| `summary` | <1 | `summary.json` — terminal label and Q1–Q13 answers |

`--limit N` caps the trade count for a smoke test. **Never** use it for a
reported result; it silently shrinks every denominator.

### Phase 0 is a hard gate

`build` stops outright if the accepted predecessor population does not reproduce.
This study does not repair a predecessor silently. The three quantities that are
easy to get wrong, and their authority
(`post_confirm_profit_ratchet/implementation/validate.py:167-177`):

- **entries = 8,950** comes from the ARMED panel. `confirmed_population()` is a
  filtered view of it (4,705 rows) and can never supply this count or the
  stopped-before-confirm cohort.
- **pool** sums giveback over `nat_kind == "OPPOSING_FLIP"` terminals only. STOP
  and SESSION terminals never gave anything back to recover.
- **baseline** is the confirmed cohort's net **plus** the 4,245 trades stopped
  before they ever confirmed. Omitting that cohort is not a smaller baseline, it
  is a different strategy — the losers the entry rule pays for before any exit
  rule can act.

## Module map

| Module | Responsibility |
|---|---|
| `common.py` | Frozen grids, population loaders, seal check, trade-clustered bootstrap. Nothing here is optimisable. |
| `arms.py` | The causal walk. Rung index, retracement arm, frozen recovery anchors, recovery scan, placebo draw. |
| `build.py` | Walks every trade once into the two panels; Phase 0 lineage reconciliation. |
| `phases.py` | Descriptive and economic aggregation. Groups the panels; never re-walks a path. |
| `diagnostics.py` | Price-only rules, the six §7.5 controls, side and year splits. |
| `validate.py` | The 14 SPEC gates, re-derived independently of the panels where possible. |

Nothing downstream of `build` recomputes a path, so a descriptive table cannot
disagree with the causal walk that produced it.

## Conventions that bite

**Two paths, always labelled.** `UNCONSTRAINED` is the descriptive path and
ignores the stop; `STOP_LIVE` is the tradeable one. Descriptive tables use
UNCONSTRAINED by design (SPEC §4); every economics table filters
`arm_stop_live_reachable & alive_stop_live`. A number without its `path` label is
meaningless.

**The arm is intrabar and causal.** The arm bar is the first bar after the rung
whose LOW breaches the high-water mark *through the previous completed bar*
(`hwm_prev[k] = run_mfe[k-1]`). Using the running extremum here would let the arm
contain its own answer.

**Recovery anchors are frozen at the arm.** `HWM_ARM` and `MARK_ARM` are captured
once at bar `a`; every target is an affine function of them and the scan starts at
`a+1`.

**`ARM_CLOSED_AT_HWM` is excluded from recovery primaries.** When the arm bar
spikes down but closes at or above the old high-water mark, `DD <= 0` and the
recovery target sits below the arm bar's own close — recovery is satisfied at
t=0 by construction. Counted in `retracement_frequency.csv`, excluded everywhere
recovery timing or probability is reported, with `n_arm_closed_at_hwm_excluded`
carried alongside so the partition still reconciles.

**EXIT NOW is priced at the fill, never the high-water mark.** `exit_now_mark_atr`
is bar `j+1`'s OPEN. The HWM price exists only as
`exit_now_hwm_atr_CONTRAST_ONLY` and gate V3 fails the build if any unsuffixed
reference appears. An HWM-priced exit is not a reachable fill; 61.6% of the
predecessor's headline vanished when it was marked properly.

**Conditional statistics are never reported alone.** Gate V7 forbids emitting a
median time-to-recovery without `p_recovered` on the same row. A fast median over
a cohort that mostly never recovers is not a fast recovery.

**Underpowered cells are suppressed, not hidden.** Below 20 unique trades,
quantiles and bootstrap CIs emit NULL with `underpowered = true` and the count
left visible. The bootstrap resamples unique **trades**, not observations — one
trade contributing six rung-cells contributes all six or none.

**The placebo is length-blind.** Offsets are drawn from a fixed grid, never from
the realised lifetime. A uniform draw over realised life is itself lookahead.

## Audit

```bash
python scripts/causal_lint.py --study studies/post_confirm_retracement_recovery
python -m pytest studies/post_confirm_retracement_recovery/tests/ -q
```

Then `lookahead-auditor` (causality) and `contract-checker` (deliverables).
Gates read `audit/status.json`, never prose.
