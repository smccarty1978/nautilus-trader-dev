import os
import sys
import subprocess
import webbrowser
import time

def install_missing_packages():
    """Verify that required dependencies are installed, installing them if missing."""
    required = ["fastapi", "uvicorn", "pandas", "pyarrow"]
    missing = []
    
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            # Handle standard imports vs package name mapping
            if pkg == "pyarrow":
                try:
                    import pyarrow
                except ImportError:
                    missing.append("pyarrow")
            else:
                missing.append(pkg)
                
    if missing:
        print(f"Detected missing packages required for visualizer: {missing}")
        print("Installing packages using pip...")
        try:
            # Prefer uv if available since it is 10x faster
            subprocess.check_call(["uv", "pip", "install"] + missing)
            print("Successfully installed missing packages with uv.")
        except Exception:
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
                print("Successfully installed missing packages with pip.")
            except Exception as e:
                print(f"Failed to install packages: {e}")
                sys.exit(1)


def main():
    # 1. Install dependencies
    install_missing_packages()
    
    # 2. Add current directory to python path so uvicorn can find the modules
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    os.environ["PYTHONPATH"] = os.path.abspath(os.path.dirname(__file__))

    port = 8000
    url = f"http://localhost:{port}"
    
    print("\n" + "=" * 60)
    print("      NAUTILUS TRADER BACKTEST VISUALIZER LAUNCHER")
    print("=" * 60)
    print(f"1. Open your browser to: {url}")
    print("2. Select a backtest from the dropdown.")
    print("3. Click trades to visualize candles, stops, and EMAs.")
    print("4. Press Ctrl+C in this terminal to stop the server.")
    print("=" * 60 + "\n")

    # 3. Open the web browser automatically after a short delay
    # We do a small timer in a background thread or just run webbrowser.open before launching uvicorn.
    # Uvicorn blocks the main thread, so we open the browser first.
    def open_browser():
        time.sleep(1.5)
        print("Opening browser...")
        webbrowser.open(url)

    import threading
    threading.Thread(target=open_browser, daemon=True).start()

    # 4. Start Uvicorn server
    import uvicorn
    uvicorn.run("utils.visualizer:app", host="127.0.0.1", port=port, log_level="info", reload=False)


if __name__ == "__main__":
    main()
