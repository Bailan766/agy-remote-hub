@echo off
chcp 65001 >nul
title Antigravity Pocket Companion Launcher
cd /d "%~dp0"

echo ========================================================
echo   ⚡ Antigravity Pocket - 手机控制连接中心
echo ========================================================
echo 正在启动后台服务与桌面控制台...

python launcher_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [警告] GUI 启动失败，切换到控制台服务模式...
    python server.py
)
pause
