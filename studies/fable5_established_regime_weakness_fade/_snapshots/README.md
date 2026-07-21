# Snapshot provenance (read before diffing)

- `results_20260713_1340/` — Stage-1 artifacts AND the ORIGINAL BROKEN
  Stage-2 2025 run (2,403 trades, F1 fillna(regime) direction bug). Taken
  before the loader fix landed.
- `stage2_broken_direction_20260713_1335/` — MISNAMED: the 2025 files here
  are byte-identical to the corrected current output (the folder was filled
  after an intermediate regeneration); the 2026 files are from the broken
  premature run. Use results_20260713_1340/ for the true broken 2025
  baseline. Current corrected results live in `../results/`.
