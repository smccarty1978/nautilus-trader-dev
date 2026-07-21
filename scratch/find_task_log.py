import os

print("Searching under APPDATA...")
base_path = r"C:\Users\Scott McCarty\.gemini\antigravity"
found = False
for root, dirs, files in os.walk(base_path):
    for f in files:
        if "task-1548" in f:
            print(os.path.join(root, f))
            found = True

if not found:
    print("Could not find any files with 'task-1548'")
