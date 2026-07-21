import re

content = open("studies/1m_regime_collector_v2/collector.py", "r", encoding="utf-8").read()

# Let's search for EMA or regime logic
for line in content.splitlines():
    if any(x in line for x in ["ema3", "ema9", "ALPHA", "regime", "flip"]):
        print(line.strip())
