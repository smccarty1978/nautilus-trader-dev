# Phase D Full-Path Build Estimate

Accepted Phase C population:

- Selected trades: **5,836**
- Long: **2,507**
- Short: **3,329**
- Planned completed fallback paths: **5,836**
- Planned censored paths from the accepted flip ledger: **0**

Path scale:

- Estimated one-second path rows: **7,841,160**
- Median decision-to-fallback duration: **950 seconds**
- p95 duration: **2,995 seconds**
- Maximum duration: **192,870 seconds**
- Maximum overlapping canonical trades: **4**
- Largest entry-month estimate: **316,870 rows** (July 2024)

Resource plan:

- Build one entry month at a time inside NautilusTrader.
- Keep one month of path rows in memory, then write atomically.
- Expected compressed path size: approximately **2–6 GB**.
- Peak-memory target: **under 8 GB**.
- Available disk at estimation: approximately **444 GB**.
- Expected runtime: **30–90 minutes**, followed by exact parity and raw-bar
  validation.

The estimate counts elapsed seconds through the accepted fallback flip. Actual
path rows may be lower where the catalog contains explicit no-bar intervals.
