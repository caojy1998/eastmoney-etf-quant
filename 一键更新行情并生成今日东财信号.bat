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

for /f "delims=" %%i in ('where python 2^>nul') do (
    echo %%i | findstr /i "WindowsApps" >nul
    if errorlevel 1 (
        "%%i" -c "import numpy, pandas, PIL" >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=%%i"
            goto :run_steps
        )
    )
)

echo ==========================================================================
echo [错误] 未找到可用的 Python 环境（且无法自动初始化），已中止打开旧网页！
echo        若您更换了新电脑，请先安装 Python (勾选 Add to PATH) 并执行:
echo        pip install -r requirements.txt
echo ==========================================================================
pause
exit /b 1

:run_steps
echo [1/4] 正在拉取东方财富 / 腾讯财经最新行情与实时折溢价...
"%PYTHON_EXE%" fetch_eastmoney_data.py
if errorlevel 1 goto :err

echo [2/4] 正在运行 6 年严格实盘级回测校验...
"%PYTHON_EXE%" backtest_engine.py
if errorlevel 1 goto :err

echo [3/4] 正在计算今日实盘账户收益与调仓差额信号...
"%PYTHON_EXE%" eastmoney_live_signal.py
if errorlevel 1 goto :err

echo [4/4] 正在生成最新可视化图表与交互式看板...
"%PYTHON_EXE%" generate_visuals.py
if errorlevel 1 goto :err

start "" "%~dp0output\dashboard.html"
pause
exit /b 0

:err
echo.
echo ==========================================================================
echo [错误] 脚本执行过程中出现异常（请查看上方报错信息）！
echo        为防止误看旧数据，本次未自动弹出旧的 dashboard.html 看板。
echo ==========================================================================
pause
exit /b 1
