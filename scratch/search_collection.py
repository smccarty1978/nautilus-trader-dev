import os

for fn in ["studies/1m_regime_collector_v2/run_collection.py", "studies/1m_regime_collector_v2/run_6year_overnight.py"]:
    print(f"File: {fn}")
    content = open(fn, "r", encoding="utf-8").read()
    for line in content.splitlines():
        if any(x in line for x in ["filter", "RTH", "session", "hour", "volume", "vol >", "exclude", "drop", "skip"]):
            print("  ", line.strip())
