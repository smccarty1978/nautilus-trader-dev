content = open("studies/1m_regime_collector_v2/collector.py", "r", encoding="utf-8").read()

lines = content.splitlines()
for i, l in enumerate(lines):
    if "_warmup_complete =" in l or "self.atr_14.initialized" in l:
        for j in range(max(0, i-2), min(len(lines), i+8)):
            print(f"{j+1}: {lines[j]}")
        print("-" * 50)
