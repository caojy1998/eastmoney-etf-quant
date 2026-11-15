@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"

if exist "%PYTHON_EXE%" goto :run_steps

if exist "%UV_EXE%" (
    "%UV_EXE%" venv "%~dp0.venv" --python 3.12
    "%UV_EXE%" pip install --python "%PYTHON_EXE%" -r "%~dp0requirements.txt"
)
if exist "%PYTHON_EXE%" goto :run_steps

echo ==========================================================================
echo [错误] 未找到本地 Python 环境 (.venv)，无法同步持仓！
echo ==========================================================================
pause
exit /b 1

:run_steps
"%PYTHON_EXE%" sync_holdings.py
if errorlevel 1 goto :err

"%PYTHON_EXE%" eastmoney_live_signal.py
if errorlevel 1 goto :err

"%PYTHON_EXE%" generate_visuals.py
if errorlevel 1 goto :err

pause
exit /b 0

:err
echo.
echo ==========================================================================
echo [错误] 同步持仓或刷新看板失败，请检查上方提示信息！
echo ==========================================================================
pause
exit /b 1
