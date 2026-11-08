@echo off
chcp 65001 >nul
set PYTHON_EXE=C:\Users\zero-max\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
cd /d "%~dp0"
"%PYTHON_EXE%" sync_holdings.py
"%PYTHON_EXE%" eastmoney_live_signal.py
"%PYTHON_EXE%" generate_visuals.py
pause
