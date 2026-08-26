@echo off
echo =========================================================
echo  Starting Nautilus Trader - KNN HEALTH (hC) Visualizer
echo  (separate instance, port 8001)
echo =========================================================
echo.
python scripts/visualizer/run_visualizer_hc.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start hC visualizer. Please check python environment.
    pause
)
