import os
import glob

# Search in the system generated tasks folder for task-1548.log
appdata_dir = os.environ.get("APPDATA", r"C:\Users\Scott McCarty\AppData\Roaming")
# Wait, let's search under the brain folder for task-1548.log
brain_dir = r"C:\Users\Scott McCarty\.gemini\antigravity\brain\4fdd02ec-1907-476c-9ead-197f2f1dcf52\.system_generated\tasks"
log_file = os.path.join(brain_dir, "task-1548.log")

if os.path.exists(log_file):
    print(f"Log file {log_file} exists!")
    with open(log_file, "r") as f:
        lines = f.readlines()
        print("Last 20 lines of the task log:")
        for line in lines[-20:]:
            print(line, end="")
else:
    print(f"Log file {log_file} does NOT exist. Let's search under brain_dir:")
    for root, dirs, files in os.walk(r"C:\Users\Scott McCarty\.gemini\antigravity\brain"):
        for f in files:
            if "task-1548" in f:
                print(os.path.join(root, f))
