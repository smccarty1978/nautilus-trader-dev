@echo off
echo =========================================================
echo  Starting Nautilus Trader Backtest Visualizer Dashboard 
echo =========================================================
echo.
python run_visualizer.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start visualizer. Please check python environment.
    pause
)
