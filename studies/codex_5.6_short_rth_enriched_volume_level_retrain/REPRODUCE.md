# Reproduction

Do not run before the independent pre-execution audit has recorded zero CRITICAL and zero WARNING in `audit/audit.md`.

```powershell
python studies/codex_5.6_short_rth_enriched_volume_level_retrain/run_study.py select_2025
python studies/codex_5.6_short_rth_enriched_volume_level_retrain/run_study.py evaluate_2026
```

The first command must not open 2026. It writes `_work/selection_seal.json` atomically. The second verifies that seal, code, manifest, and baseline hashes before it opens `full_2026.parquet`. Inputs, schema, row count, key uniqueness, class map, registry status, and feature dimensions fail closed. The 807-trade schedule overlay is non-blocking only: any mismatch is `NOT_APPLICABLE` and cannot support a favorable claim.

Stage 1 reads only the hash-pinned, project-local `baseline_2025.json`; it does not open a shared artifact containing 2026 outcomes. After the selection seal is authenticated, stage 2 verifies the hash-pinned `sealed_2026.py`, lazily loads its canonical 2026 baseline dependencies, reconciles every gate metric, and only then opens `full_2026.parquet`. Any mismatch is a parity error.
