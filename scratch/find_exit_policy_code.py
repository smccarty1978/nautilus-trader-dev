import glob
import os

files = glob.glob("**/*.py", recursive=True) + glob.glob("**/*.md", recursive=True)
for f in files:
    if ".claude" in f or ".system_generated" in f or "node_modules" in f:
        continue
    try:
        with open(f, "r", encoding="utf-8", errors="replace") as file:
            content = file.read()
            if "regime_win_bar1" in content or "regime_pnl_atr_bar1" in content or "PT%" in content or "PT trade" in content:
                print(f"Found in: {f}")
    except Exception as e:
        pass
