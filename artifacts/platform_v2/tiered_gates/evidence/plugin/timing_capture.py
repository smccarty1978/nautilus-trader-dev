"""pytest plugin: append one JSON line per test phase as it completes (partial results readable any time)."""
import json, os, time

_PATH = os.environ.get("TIMING_CAPTURE_PATH", "timing.jsonl")
_START = time.time()


def pytest_runtest_logreport(report):
    with open(_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"nodeid": report.nodeid, "phase": report.when, "outcome": report.outcome,
                             "seconds": report.duration, "t": round(time.time() - _START, 3)}) + "\n")


def pytest_sessionfinish(session, exitstatus):
    with open(_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"session_finished": True, "exitstatus": int(exitstatus), "wall": round(time.time() - _START, 3)}) + "\n")
