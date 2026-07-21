# Antigravity Agent Workflow

This workspace supports delegating tasks to specialized subagents to optimize context usage and control API costs. 

When running in **Antigravity**, these subagents run natively using Google Gemini models, which offer massive context windows and high execution speeds.

---

## Agent Roster and Gemini Model Mapping

| Subagent Name | Claude Model (Original) | Gemini Equivalent Model | Antigravity Model Flag | Purpose |
|---|---|---|---|---|
| `repo-scout` | Haiku | Gemini 3.6 Flash / Flash Lite | `flash` / `flash_lite` | Locate code and trace execution paths |
| `contract-checker` | Sonnet | Gemini Pro / 3.6 Flash | `pro` / `flash` | Verify specifications and invariant compliance |
| `results-triager` | Haiku | Gemini 3.6 Flash / Flash Lite | `flash` / `flash_lite` | Run test commands and triage results |
| `lookahead-auditor` | Sonnet | Gemini Pro | `pro` | Deep causal audit for look-ahead bias |


---

## Invoking Subagents in Antigravity

Antigravity handles subagent registration and calling natively via its model orchestration loop.

### How to Invoke
Simply request the flagship model to run the task on a subagent. For example:
> *"Invoke lookahead-auditor on strategies/short_rth_entry_surface_backfill/"*

The flagship model will use the `invoke_subagent` tool with the corresponding prompt template and target model flag.

### Coordination Rules
* **Parallel Checks**: Multiple read-only subagents (`repo-scout`, `contract-checker`) can run in parallel safely.
* **Context Preservation**: Subagents return condensed Markdown summaries rather than raw code dumps to keep the main conversation context clean.
* **Audit Enforcement**: The `lookahead-auditor` must be run on any modified strategy or data-loading script before declaring a study complete.

---

## Lean Workflow Coordination & Token Minimization

### 1. Risk Tiering & Gates
Before starting any task, the main session classifies the work into a risk tier:
* **Tier 1 (Small Diagnostic)**: Main session $\rightarrow$ run deterministic tests $\rightarrow$ local smoke check. No planning or audit agents.
* **Tier 2 (Normal Research)**: Planning agent $\rightarrow$ main session implementation $\rightarrow$ staged runner $\rightarrow$ independent completion auditor.
* **Tier 3 (Model Freeze / Deploy)**: `repo-scout` $\rightarrow$ `contract-checker` $\rightarrow$ main session implementation $\rightarrow$ staged runner $\rightarrow$ independent completion auditor.

### 2. Output Word Limits
All subagents must strictly obey role-specific output limits to minimize token generation costs:
* `repo-scout`: Max 700 words. Paths and symbols only.
* `contract-checker`: Max 1,000 words. Compliance table and findings only.
* `results-triager`: Max 500 words. Root cause test failures only.
* `lookahead-auditor`: Max 1,500 words. Findings sorted by severity only.

### 3. Contextual Diff Audits
Audits are executed "diff-first" using a contextual patch (`git diff -U20`). Full source files are only read if structural context or dependencies are unresolved in the diff. Unchanged files are not reopened unless necessary.

### 4. Deterministic Run Bounding
Process monitoring, execution stats, timeouts, and stalled run detection are handled by the deterministic wrapper `scripts/run_bounded_study.py`. Do not invoke results-triager or runtime controller agents for simple runs.

