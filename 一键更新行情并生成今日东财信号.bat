@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "UV_EXE=%USERPROFILE%\.local\bin\uv.exe"

if exist "%PYTHON_EXE%" goto :run_steps

echo [提示] 未检测到本地独立 Python 环境 (.venv)，正在尝试用 uv 自动初始化...
if exist "%UV_EXE%" (
    "%UV_EXE%" venv "%~dp0.venv" --python 3.12
    "%UV_EXE%" pip install --python "%PYTHON_EXE%" -r "%~dp0requirements.txt"
)
if exist "%PYTHON_EXE%" goto :run_steps

where python >nul 2>nul
if not errorlevel 1 (
    for /f "delims=" %%i in ('where python') do (
        echo %%i | findstr /i "WindowsApps" >nul
        if errorlevel 1 (
            set "PYTHON_EXE=%%i"
            goto :run_steps
        )
    )
)

echo ==========================================================================
echo [错误] 未找到可用的 Python 解释器！已中止打开网页，防止误看旧缓存数据。
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
