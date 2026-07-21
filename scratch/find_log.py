import os
from pathlib import Path

def find_file(root, name):
    for r, d, files in os.walk(root):
        for f in files:
            if name in f:
                print(f"Found: {Path(r) / f}")

find_file("C:/Users/Scott McCarty/.gemini/antigravity/brain/4fdd02ec-1907-476c-9ead-197f2f1dcf52", "task-5991")
