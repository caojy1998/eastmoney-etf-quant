@echo off
chcp 65001 >nul
echo ======================================================================
echo   东方财富 6万元本金 场内ETF量化系统 - 一键行情更新与今日实盘信号生成
echo ======================================================================
set PYTHON_EXE=C:\Users\zero-max\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe

cd /d "%~dp0"
"%PYTHON_EXE%" fetch_eastmoney_data.py
"%PYTHON_EXE%" backtest_engine.py
"%PYTHON_EXE%" eastmoney_live_signal.py
"%PYTHON_EXE%" generate_visuals.py

echo.
echo [完成] 正在打开可视化实盘看板 (output\dashboard.html)...
start "" "%~dp0output\dashboard.html"
pause
