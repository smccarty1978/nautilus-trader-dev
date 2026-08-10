# Armed Fade Score-Path Progression and MAE-to-Flip

Discovery study on the regime-complete canonical store. Asks whether the Top-10%
fade-model threshold can serve as an **arm** — an early warning that a setup is
forming — and whether the score's subsequent progression to Top-5 / 2.5 / 1
identifies the subset of regimes that will actually reach their confirming flip.
Secondarily, it measures how much adverse excursion the successful flips
genuinely require.

Frozen contract: [`SPEC.md`](SPEC.md). Results: [`REPORT.md`](REPORT.md).

**This is a path and probability study, not a policy search.** No parameter is
tuned against an outcome and no production winner is designated. Its predecessor,
`studies/model_driven_entry_exit_discovery/`, is sealed `DISCOVERY_NEGATIVE`
(0 of 65 entry and 0 of 18 exit configurations net-positive against these frozen
models); this study inherits that prior.

---

## The two walks

The single most important thing to know when reading any artifact here is which
walk produced it. They are never pooled.

| | Walk A — arm-anchored | Walk B — per-level independent |
|---|---|---|
| Entries per regime | 1, at the Top-10 arm | up to 4, one per level reached |
| Reference price / ATR | frozen at the arm | frozen at each level's own dispatch |
| 1.0 ATR stop measured from | the arm | each level's own entry |
| Deeper levels are | conditioning milestones that subset the population | independent entry points |
| Answers | "does Top-10 arm, and does progression sort the survivors?" | "what would entering at Top-5 instead have cost and gained?" |

`walk_b_*_top10` and `walk_a_*` are the same measurement by construction; SPEC §9
gate 4 asserts they agree.

## The two MAE populations

Equally important. `mae_to_confirm_by_level.json` reports both:

- **`uncensored`** — every entry reaching the confirming flip before the session
  close, *no stop applied*. **Read the study's stop-room answer from here.**
- **`censored_1atr`** — only entries confirming before a 1.0 ATR adverse
  excursion. Bounded above by 1.0 ATR *by construction*, so its 1.00-ATR
  survival row is necessarily 100% and its p90/p95 are truncation artifacts. It
  is included because it is the Walk A survivor population, not because it
  answers the question.

---

## Reproducing

Run in order from the repository root. Arming requires the full 2021–2025
population and will raise if given a partial slice.

```bash
python scripts/causal_lint.py --study studies/armed_fade_score_path_progression \
    --json studies/armed_fade_score_path_progression/audit/lint.json
python -m pytest studies/armed_fade_score_path_progression/tests -q

python -m studies.armed_fade_score_path_progression.implementation.build_paths
python -m studies.armed_fade_score_path_progression.analysis.diagnostics
python -m studies.armed_fade_score_path_progression.implementation.validate
```

`build_paths` is the only expensive step (it loads 28.4M RTH 1s bars); the
diagnostics and validation run against its parquet output.

## Module map

| Path | Role |
|---|---|
| `implementation/arming.py` | observation stream, arm detection, level reach, score-path shape |
| `implementation/walks.py` | `measure_to_confirm` — the shared causal path primitive for both walks |
| `implementation/build_paths.py` | builds `results/armed_regime_score_paths.parquet`, one row per armed regime |
| `analysis/diagnostics.py` | every SPEC §8 artifact, as queries over that parquet |
| `implementation/validate.py` | the eight SPEC §9 gates → `results/validation_report.json` |
| `tests/` | deterministic unit tests on synthetic bars and synthetic score frames |

Upstream, reused unmodified and already accepted:
`studies/model_driven_entry_exit_discovery/implementation/engine.py`
(`MarketData`, `RegimeIndex`, `load_market`, `load_regimes`) and
`candidates.py` (`THRESHOLDS`, `load_scored`).

## Conventions that are easy to get wrong

- **Unscored dispatches are dropped.** ~8% of in-domain dispatches carry a null
  probability. A null is not evidence of "below threshold", and it NaN-poisons
  every running maximum it touches. See SPEC §2.1a.
- **Arming never runs on a year slice.** The from-below test reads each regime's
  predecessor dispatch; filtering years first drops it at every boundary and
  manufactures phantom crossings. Year breakdowns slice the finished table.
- **The confirming flip resolves inclusively.** A flip stamped at second T is
  knowable only after a decision made at T, under the 1s-before-1m convention.
- **Windows are clamped to the entry's own RTH session.** Only RTH bars are
  loaded, so index i+1 after 14:59:59 is the next session's 08:30.
- **A stop fills at the following bar's open**, never at the trigger price.
- **2025 is not threshold-out-of-sample.** Both calibration populations are
  calendar-2025 and overlap the evaluation window. The canonical waiver is
  `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`, the path the
  store's own `waiver_artifact` column carries for all six percentiles; this
  study inherits it rather than forking a local copy.

## Audit trail

| Pass | Gate | Verdict |
|---|---|---|
| `audit/lint.json` | `causal_lint` | 0 CRITICAL / 0 WARNING |
| `audit/pass_01.md` | `lookahead-auditor`, pre-execution | PASS — 0 CRITICAL, 1 WARNING, 2 notes |
| `audit/pass_02.md` | `lookahead-auditor`, bounded re-audit | PASS — 0 CRITICAL, all pass-1 findings resolved |
| `audit/contract_status.json` | `contract-checker` | see file |

Both auditor passes ran **before** the results reported in `REPORT.md` were
generated, per the project's pre-execution audit gate.
