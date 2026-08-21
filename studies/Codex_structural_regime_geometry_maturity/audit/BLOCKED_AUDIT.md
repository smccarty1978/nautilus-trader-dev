# Mandatory audit gate blocked

Date: 2026-08-14

`lookahead_auditor` and `contract_checker` were each invoked twice on the frozen
study scope after a clean deterministic lint. Neither audit started: the Codex
runtime returned HTTP 400, `gemini-3.5-pro model is not supported when using Codex
with a ChatGPT account.` The canonical Codex definitions were then changed to
`gpt-5.6-sol` and regenerated; retries within this already-running task still used
the cached Gemini role definition. Start a new Codex task to load the regenerated
auditors.

This is an environment capability failure, not a clean audit verdict. The study is
therefore not accepted, no deployment conclusion is authorized, and the requested
knowledge-base export must wait for both independent audit statuses to be clean.
