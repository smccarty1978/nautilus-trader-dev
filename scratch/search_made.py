content = open("studies/1m_regime_collector_v2/collector.py", "r", encoding="utf-8").read()

lines = content.splitlines()
for i, l in enumerate(lines):
    if "made =" in l or "confirmed =" in l or "bar1.h >" in l or "bar1.l <" in l:
        # print 5 lines around
        for j in range(max(0, i-2), min(len(lines), i+8)):
            print(f"{j+1}: {lines[j]}")
        print("-" * 50)
