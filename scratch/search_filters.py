content = open("studies/1m_regime_collector_v2/collector.py", "r", encoding="utf-8").read()

lines = content.splitlines()
found = False
for i, l in enumerate(lines):
    if "Apply warmup gate" in l or "skipped_" in l or "emit" in l:
        found = True
        for j in range(max(0, i-5), min(len(lines), i+15)):
            print(f"{j+1}: {lines[j]}")
        print("-" * 50)
if not found:
    print("Not found.")
