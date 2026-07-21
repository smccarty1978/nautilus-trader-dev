"""Launcher for the Model-Score Backtest Visualizer (separate from the standard
visualizer). Adds a Pane-2 panel (model score line + filter-decision ribbon +
threshold guide) for any study that writes a companion indicators.parquet next
to its trades.parquet. Originally built for the KNN hC health score; reused as
of 2026-07 for studies/rank_filter_oos_validation's frozen risk score.
Runs on port 8001 so it can coexist with the standard visualizer (port 8000).
"""
import os
import sys
import subprocess
import webbrowser
import time


def install_missing_packages():
    required = ["fastapi", "uvicorn", "pandas", "pyarrow"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"Installing missing packages: {missing}")
        try:
            subprocess.check_call(["uv", "pip", "install"] + missing)
        except Exception:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)


def main():
    install_missing_packages()
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    os.environ["PYTHONPATH"] = os.path.abspath(os.path.dirname(__file__))

    port = 8001
    url = f"http://localhost:{port}"
    print("\n" + "=" * 60)
    print("      NAUTILUS TRADER — MODEL SCORE VISUALIZER")
    print("=" * 60)
    print(f"1. Open your browser to: {url}")
    print("2. Select a run from the dropdown, e.g.:")
    print("   '[studies] rank_filter_oos_validation - r2_2025H2' / 'r4_2025H2' / 'r2_2026' / 'r4_2026'")
    print("3. Click a trade; the bottom Pane 2 shows the frozen risk score")
    print("   (orange dotted line = frozen skip threshold) + a filter-decision")
    print("   ribbon (red=SKIPPED, orange=EXEMPT-KEEP, teal=LOW-RISK-KEEP).")
    print("4. Press Ctrl+C in this terminal to stop the server.")
    print("=" * 60 + "\n")

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn
    uvicorn.run("utils.visualizer_hc:app", host="127.0.0.1", port=port,
                log_level="info", reload=False)


if __name__ == "__main__":
    main()
