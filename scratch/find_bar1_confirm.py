import os
from pathlib import Path

for path in Path("backtests").rglob("*.py"):
    try:
        content = path.read_text(encoding="utf-8")
        if "bar1" in content or "confirm" in content:
            lines = content.splitlines()
            matching = [f"{i+1}: {l.strip()}" for i, l in enumerate(lines) if "bar1" in l or "confirm" in l]
            if matching:
                print(f"File: {path}")
                for m in matching[:5]:
                    print(f"  {m}")
                if len(matching) > 5:
                    print(f"  ... and {len(matching)-5} more lines")
    except Exception as e:
        pass
