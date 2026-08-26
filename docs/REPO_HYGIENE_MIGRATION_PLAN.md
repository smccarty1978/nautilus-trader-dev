# Repository Hygiene & Migration Plan

This plan inventories all files currently at the repository root and details the proposed classification and rehoming path for each.

## 1. Classification Definitions

*   **`KEEP_ROOT`**: Main configuration and orchestration files that belong at the repository root.
*   **`MOVE_TO_DOCS_CURRENT`**: Current supporting documentation that belongs inside the `docs/` directory.
*   **`MOVE_TO_ARCHIVE_DOCS`**: Stale, superseded, or historical documents to be relocated to `archive/docs/` to preserve reasoning/audit logs without cluttering the active workspace.
*   **`MOVE_TO_ARCHIVE_FORENSICS`**: Historical gap analysis data files and forensics to be rehomed to `archive/forensics/gaps/`.
*   **`MOVE_TO_SCRIPTS`**: Shared operational and utility scripts to be rehomed to standard folders under `scripts/`.
*   **`MOVE_TO_STUDY`**: Study-specific scripts, configurations, or specifications that belong inside their respective study directories to achieve full containment.
*   **`DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT`**: Orphaned debug logs or transient run files that are safe to discard.
*   **`DESIGN_CONTRACT_PATH_MIGRATION`**: Active design contracts cited by live code. (Must be listed separately and NOT moved automatically).
*   **`NEEDS_REVIEW`**: Special files requiring developer investigation before any action.

---

## 2. Root File Inventory & Proposed Relocation Paths

| Source Path (relative to root) | Classification | Proposed Target Path | Notes & References / Cited In |
|:---|:---|:---|:---|
| `.env` | `KEEP_ROOT` | — | Environment variables. |
| `.gitignore` | `KEEP_ROOT` | — | Git ignores. To be modified to ignore `studies/*/runs/` and `studies/*/_work/`. |
| `pytest.ini` | `KEEP_ROOT` | — | Pytest configuration. |
| `AGENTS.md` | `KEEP_ROOT` | — | Authoritative agent manual. |
| `CLAUDE.md` | `KEEP_ROOT` | — | Claude manual. |
| `CODEX.md` | `KEEP_ROOT` | — | Codex manual. |
| `desktop.ini` | `KEEP_ROOT` | — | Windows directory settings. |
| `run_visualizer.bat` | `KEEP_ROOT` | — | Launcher compatibility shim (updated to call `python scripts/visualizer/run_visualizer.py`). |
| `run_visualizer_hc.bat` | `KEEP_ROOT` | — | Launcher compatibility shim (updated to call `python scripts/visualizer/run_visualizer_hc.py`). |
| `BACKTEST_DATA_LOGGING.md` | `MOVE_TO_DOCS_CURRENT` | `docs/BACKTEST_DATA_LOGGING.md` | Cited in `docs/DOCUMENT_MAP.md`. |
| `VISUALIZER_EXTENSIONS.md` | `MOVE_TO_DOCS_CURRENT` | `docs/VISUALIZER_EXTENSIONS.md` | Cited in `docs/DOCUMENT_MAP.md`. |
| `ANALYSIS_HARNESS_IMPLEMENTATION_REPORT.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/ANALYSIS_HARNESS_IMPLEMENTATION_REPORT.md` | Historical. |
| `audit.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/audit.md` | Historical audit ledger. |
| `audit_5s_scalps.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/audit_5s_scalps.md` | Historical audit ledger. |
| `audit_keltner.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/audit_keltner.md` | Historical audit ledger. |
| `audit_stall_parity.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/audit_stall_parity.md` | Historical audit ledger. |
| `BACKTEST_HARNESS_IMPLEMENTATION_REPORT.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/BACKTEST_HARNESS_IMPLEMENTATION_REPORT.md` | Historical. |
| `BACKTEST_HARNESS_REMEDIATION_REPORT.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/BACKTEST_HARNESS_REMEDIATION_REPORT.md` | Historical. |
| `BASELINE_CAPTURE_RERUN_PLAN.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/BASELINE_CAPTURE_RERUN_PLAN.md` | Historical. |
| `FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC.md` | Historical spec. |
| `FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC_REVISED.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC_REVISED.md` | Historical spec. |
| `ML_Research_Workflow_Current_State_and_Redesign.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/ML_Research_Workflow_Current_State_and_Redesign.md` | Stale design proposal. |
| `ML_Trend_Analysis_Workflow_V2_Phase1_Corrected_RFC.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/ML_Trend_Analysis_Workflow_V2_Phase1_Corrected_RFC.md` | Superseded RFC. |
| `ML_Trend_Analysis_Workflow_V2_Phase1_Corrected_RFC_v2.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/ML_Trend_Analysis_Workflow_V2_Phase1_Corrected_RFC_v2.md` | Superseded RFC. |
| `ml_trend_analysis_workflow_v2_spec.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/ml_trend_analysis_workflow_v2_spec.md` | Superseded RFC. |
| `NautilusTrader_AI_Workflow_Reference.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/NautilusTrader_AI_Workflow_Reference.md` | Stale reference manual. |
| `NT_RESEARCH_FLOW_INDEPENDENT_AUDIT_BRIEF.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/NT_RESEARCH_FLOW_INDEPENDENT_AUDIT_BRIEF.md` | Historical. |
| `PROJECT_CONTINUATION_BACKTEST_ANALYSIS_ROADMAP.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/PROJECT_CONTINUATION_BACKTEST_ANALYSIS_ROADMAP.md` | Historical. |
| `PROPOSED_COLLECTION_TO_ANALYSIS_WORKFLOW.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/PROPOSED_COLLECTION_TO_ANALYSIS_WORKFLOW.md` | Stale design proposal. |
| `REPO_ANALYSIS.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/REPO_ANALYSIS.md` | Historical. |
| `RESEARCH_AGENT_WORKFLOW_PLAYBOOK.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/RESEARCH_AGENT_WORKFLOW_PLAYBOOK.md` | Superseded playbook. |
| `RESEARCH_PARQUET_PLATFORM_BLUEPRINT.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/RESEARCH_PARQUET_PLATFORM_BLUEPRINT.md` | Superseded blueprint. |
| `RESEARCH_PARQUET_WORKFLOW_README.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/RESEARCH_PARQUET_WORKFLOW_README.md` | Superseded README. |
| `STUDIES.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/STUDIES.md` | Stale/empty study list. |
| `WORKFLOW_HARDENING_FINAL_RED_TEAM.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/WORKFLOW_HARDENING_FINAL_RED_TEAM.md` | Historical audit report. |
| `WORKFLOW_HARDENING_FINAL_REMEDIATION.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/WORKFLOW_HARDENING_FINAL_REMEDIATION.md` | Historical audit report. |
| `WORKFLOW_HARDENING_LAST_FIX_REPORT.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/WORKFLOW_HARDENING_LAST_FIX_REPORT.md` | Historical audit report. |
| `WORKFLOW_HARDENING_REMEDIATION_REPORT.md` | `MOVE_TO_ARCHIVE_DOCS` | `archive/docs/WORKFLOW_HARDENING_REMEDIATION_REPORT.md` | Historical audit report. |
| `calendar_review_required.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/calendar_review_required.csv` | Forensic gap analysis data. |
| `eth_gap_1m_impact.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/eth_gap_1m_impact.csv` | Forensic gap analysis data. |
| `eth_gap_by_year_final.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/eth_gap_by_year_final.csv` | Forensic gap analysis data. |
| `eth_gap_reclassification.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/eth_gap_reclassification.csv` | Forensic gap analysis data. |
| `eth_historical_schedule_regimes.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/eth_historical_schedule_regimes.csv` | Forensic gap analysis data. |
| `eth_open_session_unexplained.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/eth_open_session_unexplained.csv` | Forensic gap analysis data. |
| `eth_schedule_change_points.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/eth_schedule_change_points.csv` | Forensic gap analysis data. |
| `eth_schedule_forensic_summary.json` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/eth_schedule_forensic_summary.json` | Forensic gap analysis data. |
| `gap_audit_by_year_session.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/gap_audit_by_year_session.csv` | Forensic gap analysis data. |
| `gap_audit_summary.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/gap_audit_summary.csv` | Forensic gap analysis data. |
| `gap_audit_summary.json` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/gap_audit_summary.json` | Forensic gap analysis data. |
| `long_gap_classification.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/long_gap_classification.csv` | Forensic gap analysis data. |
| `long_gap_time_of_day_summary.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/long_gap_time_of_day_summary.csv` | Forensic gap analysis data. |
| `rth_gaps_over_30s_forensic.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/rth_gaps_over_30s_forensic.csv` | Forensic gap analysis data. |
| `rth_gap_1m_impact.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/rth_gap_1m_impact.csv` | Forensic gap analysis data. |
| `rth_gap_forensic_summary.json` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/rth_gap_forensic_summary.json` | Forensic gap analysis data. |
| `rth_gap_recent_2021_2026.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/rth_gap_recent_2021_2026.csv` | Forensic gap analysis data. |
| `unexplained_gaps_over_30s.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/unexplained_gaps_over_30s.csv` | Forensic gap analysis data. |
| `unexplained_rth_gaps_over_30s.csv` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/unexplained_rth_gaps_over_30s.csv` | Forensic gap analysis data. |
| `stability_source_snapshot.json` | `MOVE_TO_ARCHIVE_FORENSICS` | `archive/forensics/gaps/stability_source_snapshot.json` | Orphaned file (noted in `docs/WORKFLOW_REFERENCE_FACTS.md` §6). |
| `check_compression_results.py` | `MOVE_TO_SCRIPTS` | `scripts/diagnostics/check_compression_results.py` | Utility script checking parquet trades. |
| `run_visualizer.py` | `MOVE_TO_SCRIPTS` | `scripts/visualizer/run_visualizer.py` | Standard visualizer launcher. |
| `run_visualizer_hc.py` | `MOVE_TO_SCRIPTS` | `scripts/visualizer/run_visualizer_hc.py` | Model score visualizer launcher. |
| `inspect_data.py` | `MOVE_TO_STUDY` | `backtests/studies/1m_regime_collector_v2/scratch/inspect_data.py` | Specific to study `1m_regime_collector_v2`. |
| `scratch_analysis.py` | `MOVE_TO_STUDY` | `backtests/pre_flip_live/scratch/scratch_analysis.py` | Specific to study `pre_flip_live`. |
| `run_dna_pipeline.cmd` | `MOVE_TO_STUDY` | `backtests/studies/regime_dna_knn/run_dna_pipeline.cmd` | Bounded script running DNA KNN pipelines. |
| `FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC_FINAL.md` | `MOVE_TO_STUDY` | `studies/full_trade_path_builder/FULL_TRADE_PATH_DUAL_MODEL_BUILDER_SPEC_FINAL.md` | Specific to study `full_trade_path_builder`. |
| `overnight.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `DBG-001_2026-07-08_480378b0-01c0-4ab4-aac0-0494c0640542.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PASS7-PROBE-B4_2026-07-08_729afca8-c8a9-4fe8-a23e-fa4b3638227d.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PASS7-PROBE-B4_2026-07-08_803499a7-9516-4021-ac8d-fd642182f1d5.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PASS7-PROBE_2026-07-08_b4eeac4a-4a73-4171-86ac-35912feec649.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PROBE-001_2026-07-08_21df3a85-1d7a-4c93-968c-6e61604ab906.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PROBE-001_2026-07-08_25ed9e97-1b1b-4f9f-a07e-d36f5eda19db.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PROBE-001_2026-07-08_ff78b982-fa7a-4e91-9cb9-df857db4d1f2.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PROBE9-001_2026-07-09_13ed1fee-74f3-4c0a-a014-e8a63d880600.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PROBE9-001_2026-07-09_2dd37ecb-dc11-4c8b-94e1-40217a607484.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PROBE9-001_2026-07-09_5ba64906-5f43-4126-bcc3-c8e7a1bfe10c.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `PROBE9-001_2026-07-09_b441ad7c-0536-4090-bcdd-b6da1999c41b.log` | `DELETE_ONLY_IF_GIT_HISTORY_SUFFICIENT` | — | Temporary logger output. |
| `nul` | `NEEDS_REVIEW` | — | Windows-reserved special name. Do not touch or attempt to move/delete. |

---

## 3. DESIGN_CONTRACT_PATH_MIGRATION (Excluded from Phase 2 Moves)

These files are active design contracts referenced in code/logic. They must **not** be moved during the low-risk Phase 2 cleanup. Moving them is a separate refactoring and reference-migration task.

*   `ANALYSIS_HARNESS_A0_CONTRACT.md`
    *   **Proposed Target Path**: `docs/design_contracts/ANALYSIS_HARNESS_A0_CONTRACT.md`
    *   **References**:
        *   `research/analysis/__init__.py:3`
        *   `research/analysis/errors.py:3`
        *   `scripts/tests/test_analysis_reproducibility.py:3`
        *   `docs/DOCUMENT_MAP.md`
        *   `docs/RESEARCH_WORKFLOW.md`
*   `BACKTEST_HARNESS_B0_BOUNDARY.md`
    *   **Proposed Target Path**: `docs/design_contracts/BACKTEST_HARNESS_B0_BOUNDARY.md`
    *   **References**:
        *   `backtests/nt_runtime/engine_builder.py:107`
        *   `docs/DOCUMENT_MAP.md`
        *   `docs/RESEARCH_WORKFLOW.md`
*   `ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md`
    *   **Proposed Target Path**: `docs/design_contracts/ML_Trend_Analysis_Workflow_V2_Phase1_FINAL.md`
    *   **References**:
        *   `research_workflow/readiness.py:10`
        *   `scripts/tests/test_readiness.py:3`
        *   `docs/DOCUMENT_MAP.md`
        *   `docs/RESEARCH_WORKFLOW.md`
        *   `docs/ERROR_REGISTRY.md`

---

## 4. Current Global Output Locations & Producing Studies

All historical run results are generated in the `runs/` folder at the repository root. Below are the key folders under `runs/` and their producing studies:

1.  `runs/2026*_*reconstructed_long_rth_strict_retrain_day`
    *   **Producing Study**: `studies/reconstructed_long_rth_strict_retrain`
2.  `runs/2026*_*Gemini_clean_maturity_flip_rolling_5m_productivity_full` (and `_day`)
    *   **Producing Study**: `studies/Gemini_clean_maturity_flip_rolling_5m_productivity`
3.  `runs/2026*_*Codex_clean_maturity_flip_rolling_5m_productivity_day`
    *   **Producing Study**: `studies/Codex_clean_maturity_flip_rolling_5m_productivity`
4.  `runs/2026*_*es_wick_imbalance_exploratory_day`
    *   **Producing Study**: `studies/es_wick_imbalance_exploratory`
5.  `runs/2026*_*es_wick_imbalance_acceptance_v2_day`
    *   **Producing Study**: `studies/es_wick_imbalance_acceptance_v2`
6.  `runs/2026*_*ym_prev5_range_position_day`
    *   **Producing Study**: `studies/ym_prev5_range_position`
7.  `runs/2026*_*clean_maturity_flip_model_rolling_productivity_day` (and `_full`)
    *   **Producing Study**: `studies/clean_maturity_flip_model_rolling_productivity`
8.  `runs/2026*_*test_minimal_checkpoint_collector_day`
    *   **Producing Study**: `studies/test_minimal_checkpoint_collector` (Or staging collector test)
9.  `runs/2026*_*test_level_break_collector_day`
    *   **Producing Study**: `studies/test_level_break_collector` (Or staging collector test)
10. `runs/ablation_*` and `runs/collector_ablations_*`
    *   **Producing Study**: Multi-model/matrix ablation test suite runs.
11. `runs/oos_repaired`, `runs/train_repaired`, `runs/oos_2024`, `runs/train_2021`, etc.
    *   **Producing Study**: `studies/clean_maturity_flip_model_rolling_productivity` (or sister retrain validation suites)
