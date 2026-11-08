@echo off
chcp 65001 >nul
cd /d "%~dp0"
set GIT_EXE=C:\Users\zero-max\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd\git.exe
set GCM_EXE=C:\Users\zero-max\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\ucrt64\bin\git-credential-manager.exe

echo ==========================================================================
echo 🚀 东方财富场内 ETF 量化系统 —— 一键上传至 GitHub
echo ==========================================================================
echo.
set /p REPO_URL="请粘贴你在 GitHub 新建的仓库地址 (例如 https://github.com/你的用户名/eastmoney-etf-quant.git): "
if "%REPO_URL%"=="" (
    echo [错误] 仓库地址不能为空！请先在 https://github.com/new 创建一个空仓库。
    pause
    exit /b 1
)

echo.
echo [1/2] 正在配置远程 GitHub 仓库地址...
"%GIT_EXE%" remote remove origin 2>nul
"%GIT_EXE%" remote add origin %REPO_URL%
"%GIT_EXE%" branch -M main

echo.
echo [2/2] 正在推送到 GitHub (若弹出 GitHub 浏览器登录框，请登录 caojy1998@163.com 点击 Authorize 授权)...
"%GIT_EXE%" push -u origin main

echo.
echo ==========================================================================
echo ✅ 如果上方显示 "branch 'main' set up to track 'origin/main'"，说明上传成功！
echo ==========================================================================
pause
