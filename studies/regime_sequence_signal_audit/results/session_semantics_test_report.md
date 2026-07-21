# CME Session Semantics Test Report

### Inclusivity Rules
* **RTH Start:** `08:30:00` Central (Inclusive)
* **RTH End:** `15:15:00` Central (Inclusive)
* **Inclusivity Rule at 15:15:00:** The time 15:15:00 is labeled **RTH**, while 15:15:01 is **ETH**.

### Unit Test Results

| Test Description | Chicago Time | UTC Timestamp | Expected | Actual | Status |
|---|---|---|---|---|---|
| exactly 08:29:59 Central (Before RTH) | `2025-06-13 08:29:59` | `2025-06-13 13:29:59+00:00` | **ETH** | **ETH** | `PASS` |
| exactly 08:30:00 Central (RTH Start) | `2025-06-13 08:30:00` | `2025-06-13 13:30:00+00:00` | **RTH** | **RTH** | `PASS` |
| exactly 15:15:00 Central (RTH Close) | `2025-06-13 15:15:00` | `2025-06-13 20:15:00+00:00` | **RTH** | **RTH** | `PASS` |
| immediately after 15:15:00 Central (After RTH) | `2025-06-13 15:15:01` | `2025-06-13 20:15:01+00:00` | **ETH** | **ETH** | `PASS` |
| DST Spring Transition - RTH Start (CDT) | `2025-03-10 08:30:00` | `2025-03-10 13:30:00+00:00` | **RTH** | **RTH** | `PASS` |
| DST Fall Transition - RTH Start (CST) | `2025-11-03 08:30:00` | `2025-11-03 14:30:00+00:00` | **RTH** | **RTH** | `PASS` |
| Sunday Evening Reopen (17:00 Central) | `2025-06-15 17:00:00` | `2025-06-15 22:00:00+00:00` | **ETH** | **ETH** | `PASS` |
| CME Maintenance halt (16:30 Central) | `2025-06-13 16:30:00` | `2025-06-13 21:30:00+00:00` | **ETH** | **ETH** | `PASS` |
| Year Boundary (Dec 31 23:59:59 Central) | `2025-12-31 23:59:59` | `2026-01-01 05:59:59+00:00` | **ETH** | **ETH** | `PASS` |
