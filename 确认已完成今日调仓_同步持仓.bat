@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"
if not exist "%UV_EXE%" (
    for /f "delims=" %%u in ('where uv 2^>nul') do (
        set "UV_EXE=%%u"
        goto :check_venv
    )
)

:check_venv
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import numpy, pandas, PIL" >nul 2>nul
    if not errorlevel 1 goto :run_steps
)

echo [提示] 正在自动初始化或修复本地独立 Python 环境 (.venv)...
if exist "%UV_EXE%" (
    "%UV_EXE%" venv --clear "%~dp0.venv" --python ">=3.11"
    "%UV_EXE%" pip install --python "%PYTHON_EXE%" -r "%~dp0requirements.txt"
)
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" -c "import numpy, pandas, PIL" >nul 2>nul
    if not errorlevel 1 goto :run_steps
)

echo ==========================================================================
echo [错误] 未找到可用的本地 Python 环境 (.venv)，无法同步持仓！
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
