# Confirmation Economics + Post-Confirmation Excursion Map

Diagnostic study of the **economic geometry** of a fade trade after the predicted
regime flip occurs. No exit grid, no trailing-stop optimization, no tuned
parameter — the point is to map the terrain before designing management rules.

Frozen contract: [`SPEC.md`](SPEC.md) · Results: [`REPORT.md`](REPORT.md)

**Verdict: `E — BOTH CONFIRMED-LOSS CONTAINMENT AND RUNNER HARVESTING WARRANT
BOUNDED POLICY STUDIES`.**

---

## The three things to know before reading any table

### 1. Two path modes, never pooled

Every trade is walked twice, and every row carries `path_mode`.

| | `constrained` | `unconstrained` |
|---|---|---|
| 1.0 ATR entry stop | live | removed **after** confirmation |
| Drives | Phases 1, 2, 8 + all terminal labels | Phases 3–7 excursion geometry |

`CONFIRMED_THEN_STOPPED` only exists if the stop is live, so the canonical
outcome tables need the constrained walk. But with the stop live, post-confirm
adverse excursion is *mechanically capped* at 1 ATR from entry — so "how much
room does a ≥3 ATR runner need" would be answered by its own premise. That
censoring trap understated p90 MAE by 5× in `armed_fade_score_path_progression`.
`terminal_label_constrained` rides on **both** rows so any table can group by
canonical outcome in either mode.

### 2. Two excursion measurements, never conflated

- **Method A — from the confirmation close.** How far below the confirm close did
  the path go. **This is the one that separates.**
- **Method B — from the running favorable extreme.** Giveback from the
  high-water mark. **Degenerate as an unconditional map**: 100% of every group
  touches every level, because by the opposing flip essentially every trade has
  given back ≥1 ATR. Reported as a null, not suppressed.

### 3. Losers and runners are measured on different clocks — deliberately

A loser never develops, so its whole post-confirmation path is fair game. A
runner must be judged on what it suffered **before first reaching its MFE
threshold** — that is the only deterioration an entry-time risk boundary could
have cut it off at. Using a whole-path maximum for runners counts giveback that
happens *after* the runner already ran, and overstates damage badly.

---

## Reproducing

```bash
python scripts/causal_lint.py --study studies/confirmation_economics_excursion_map \
    --json studies/confirmation_economics_excursion_map/audit/lint.json
python -m pytest studies/confirmation_economics_excursion_map/tests -q

python -m studies.confirmation_economics_excursion_map.implementation.panel
python -m studies.confirmation_economics_excursion_map.analysis.phases
python -m studies.confirmation_economics_excursion_map.analysis.overlay
python -m studies.confirmation_economics_excursion_map.implementation.validate
```

`panel` is the only expensive step (~25 min; 28.4M RTH 1s bars, 49,345 panel
rows). Everything else queries its parquet.

## Populations

| Population | Entries | Depth |
|---|---:|---|
| `top_10` | 8,988 | annex (Phases 1, 2, 4, 8) |
| `top_5` | 7,396 | annex |
| **`top_2_5`** | **5,823** | **all phases** |
| `top_1` | 3,415 | annex |
| **`armed`** | **8,950** | **all phases** |

All four base counts reproduce the accepted `regime_lifecycle_600s` figures
exactly; that is validation gate 1, not a courtesy check.

## Module map

| Path | Role |
|---|---|
| `implementation/panel.py` | the dual-mode per-trade walk; the only expensive step |
| `analysis/phases.py` | Phases 1–8 as queries over the panel |
| `analysis/overlay.py` | Phase 9 model overlay, exploratory out-of-domain |
| `implementation/validate.py` | the eleven SPEC §9 gates |
| `tests/test_panel.py` | 13 deterministic tests on synthetic bars |

## Conventions that are easy to get wrong

- **The measurement window opens on the bar STRICTLY AFTER entry.** Market bar 0
  is never in it. Three unit tests were initially written wrong on this point.
- **ATR is frozen at ENTRY** and normalises every excursion, including
  post-confirmation ones — that is what makes Phases 3 and 6 commensurable.
- **Landmarks already held at confirmation are excluded**, not folded in as a
  zero retrace. Median return at confirmation is +0.48 to +0.85 ATR, so the
  shallow landmarks are usually already held.
- **Floors trigger on the intrabar extreme**, matching the 1 ATR stop.
- **Same-bar collisions** (stop-vs-confirm, stop-vs-landmark, floor-vs-landmark)
  are flagged, resolved adversely, and counted. The optimistic bound is
  recoverable as `reached_after_confirm OR ambiguous_with_stop`.
- **2025 is NOT threshold-out-of-sample.** Canonical waiver:
  `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`. 2026 untouched.

## Audit trail

| Pass | Gate | Verdict |
|---|---|---|
| `audit/lint.json` | `causal_lint` | 0 CRITICAL / 0 WARNING |
| `audit/pass_01.md` | `lookahead-auditor`, pre-execution | **BLOCKED** — 2 CRITICAL |
| `audit/pass_02.md` | `lookahead-auditor`, bounded re-audit | PASS — 0 findings, both criticals resolved |
| `audit/contract_status.json` | `contract-checker` | see file |

The pre-execution gate did its job: it blocked the first full run over a Phase 7
clock-reset ordering bug and missing same-bar collision accounting, both of which
would have corrupted the headline tables.
