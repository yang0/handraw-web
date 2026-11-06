@echo off
chcp 65001 >nul
setlocal
title Handraw 服务管理
pushd "%~dp0"
if not "%~1"=="" goto command

:menu
cls
echo.
echo   Handraw 本地服务管理
echo   统一端口：3080
echo.
echo   [1] 启动服务
echo   [2] 关闭服务
echo   [3] 重启服务
echo   [4] 查看状态和访问地址
echo   [5] 打开首页
echo   [0] 退出菜单（服务继续运行）
echo.
choice /c 123450 /n /m "请选择："
if errorlevel 6 goto done
if errorlevel 5 goto open
if errorlevel 4 goto status
if errorlevel 3 goto restart
if errorlevel 2 goto stop
if errorlevel 1 goto start
goto menu

:start
set "serviceAction=start"
goto run
:stop
set "serviceAction=stop"
goto run
:restart
set "serviceAction=restart"
goto run
:status
set "serviceAction=status"
goto run

:run
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\local-service.ps1" -Action "%serviceAction%"
echo.
pause
goto menu

:open
start "" "http://localhost:3080/"
goto menu

:command
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\local-service.ps1" -Action "%~1"
set "serviceResult=%errorlevel%"
popd
exit /b %serviceResult%

:done
popd
exit /b 0
