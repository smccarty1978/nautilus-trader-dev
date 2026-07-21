import pandas as pd
from datetime import time
from pathlib import Path

PROJECT_ROOT = Path("c:/Users/Scott McCarty/Projects/Nautilus Trader")
OUT_DIR = PROJECT_ROOT / "studies/regime_sequence_signal_audit/results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def classify_session(ts_ns: int) -> str:
    """Classify session as RTH or ETH.
    
    RTH is 08:30:00 through 15:15:00 America/Chicago (inclusive at both boundaries).
    All other times (including weekends, halts, maintenance) are ETH.
    """
    ts = pd.Timestamp(ts_ns, unit='ns', tz='UTC').tz_convert('America/Chicago')
    # Weekends (Saturday and Sunday daytime before reopen)
    # Sunday reopen is at 17:00 Chicago, so Sunday is ETH.
    # ts.weekday() is 5 for Saturday, 6 for Sunday.
    if ts.weekday() >= 5:
        # Note: Sunday 17:00 is ts.weekday() == 6, which is correctly categorized as ETH.
        return "ETH"
    
    t = ts.time()
    # Inclusive check: 08:30:00 <= t <= 15:15:00 Central Time
    if time(8, 30, 0) <= t <= time(15, 15, 0):
        return "RTH"
    else:
        return "ETH"

def run_tests():
    print("Running Gate 2: Session Semantics Unit Tests...")
    
    # Test cases mapping description to UTC timestamp and expected result
    test_cases = [
        # 1. 08:29:59 Central (Normal Friday)
        {
            "desc": "exactly 08:29:59 Central (Before RTH)",
            "chicago_time": "2025-06-13 08:29:59",
            "expected": "ETH"
        },
        # 2. 08:30:00 Central (RTH Start)
        {
            "desc": "exactly 08:30:00 Central (RTH Start)",
            "chicago_time": "2025-06-13 08:30:00",
            "expected": "RTH"
        },
        # 3. 15:15:00 Central (RTH Close)
        {
            "desc": "exactly 15:15:00 Central (RTH Close)",
            "chicago_time": "2025-06-13 15:15:00",
            "expected": "RTH"
        },
        # 4. 15:15:01 Central (After RTH Close)
        {
            "desc": "immediately after 15:15:00 Central (After RTH)",
            "chicago_time": "2025-06-13 15:15:01",
            "expected": "ETH"
        },
        # 5. DST Spring Transition (March 9, 2025: Central time skips 02:00 -> 03:00)
        # 08:30 in Central DST is UTC 13:30 (CDT = UTC - 5)
        {
            "desc": "DST Spring Transition - RTH Start (CDT)",
            "chicago_time": "2025-03-10 08:30:00",
            "expected": "RTH"
        },
        # 6. DST Fall Transition (Nov 2, 2025: Central time repeats 01:00 -> 01:00)
        # 08:30 in Central EST is UTC 14:30 (CST = UTC - 6)
        {
            "desc": "DST Fall Transition - RTH Start (CST)",
            "chicago_time": "2025-11-03 08:30:00",
            "expected": "RTH"
        },
        # 7. Sunday Evening Reopen (Sunday 17:00 Chicago)
        {
            "desc": "Sunday Evening Reopen (17:00 Central)",
            "chicago_time": "2025-06-15 17:00:00",
            "expected": "ETH"
        },
        # 8. CME Maintenance Period (16:30 Central)
        {
            "desc": "CME Maintenance halt (16:30 Central)",
            "chicago_time": "2025-06-13 16:30:00",
            "expected": "ETH"
        },
        # 9. Year Boundary (Dec 31 23:59:59 Chicago)
        {
            "desc": "Year Boundary (Dec 31 23:59:59 Central)",
            "chicago_time": "2025-12-31 23:59:59",
            "expected": "ETH"
        }
    ]
    
    results = []
    failed = False
    
    for tc in test_cases:
        # Convert Chicago string to timezone-aware UTC nanoseconds
        ts_chicago = pd.Timestamp(tc["chicago_time"]).tz_localize("America/Chicago", ambiguous="NaT")
        if ts_chicago is pd.NaT:
            raise ValueError(f"Ambiguous or invalid Chicago time: {tc['chicago_time']}")
        ts_utc = ts_chicago.tz_convert("UTC")
        ts_ns = int(ts_utc.value)
        
        actual = classify_session(ts_ns)
        passed = actual == tc["expected"]
        if not passed:
            failed = True
            
        results.append({
            "description": tc["desc"],
            "chicago_time": tc["chicago_time"],
            "utc_timestamp": str(ts_utc),
            "expected": tc["expected"],
            "actual": actual,
            "passed": passed
        })
        
    df_res = pd.DataFrame(results)
    
    # Save markdown report
    md_path = OUT_DIR / "session_semantics_test_report.md"
    with open(md_path, "w") as f:
        f.write("# CME Session Semantics Test Report\n\n")
        f.write("### Inclusivity Rules\n")
        f.write("* **RTH Start:** `08:30:00` Central (Inclusive)\n")
        f.write("* **RTH End:** `15:15:00` Central (Inclusive)\n")
        f.write("* **Inclusivity Rule at 15:15:00:** The time 15:15:00 is labeled **RTH**, while 15:15:01 is **ETH**.\n\n")
        f.write("### Unit Test Results\n\n")
        f.write("| Test Description | Chicago Time | UTC Timestamp | Expected | Actual | Status |\n")
        f.write("|---|---|---|---|---|---|\n")
        for res in results:
            status = "PASS" if res["passed"] else "FAIL"
            f.write(f"| {res['description']} | `{res['chicago_time']}` | `{res['utc_timestamp']}` | **{res['expected']}** | **{res['actual']}** | `{status}` |\n")
            
    print(f"Session test report written to {md_path}")
    if failed:
        print("ERROR: One or more session semantic unit tests FAILED!")
        exit(1)
    else:
        print("All session semantic unit tests PASSED.")

if __name__ == "__main__":
    run_tests()
