import os
from pathlib import Path

def search_files(directory, keyword):
    for root, dirs, files in os.walk(directory):
        # Exclude python caches
        if "__pycache__" in root or ".git" in root or ".claude" in root or ".mypy_cache" in root:
            continue
        for file in files:
            if file.endswith(".py") or file.endswith(".ps1"):
                path = Path(root) / file
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    if keyword in content:
                        print(f"Found in: {path}")
                except Exception as e:
                    pass

search_files(".", "bar1_confirm")
