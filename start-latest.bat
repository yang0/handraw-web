@echo off
chcp 65001 >nul
title Handraw 一键启动（最新版本）
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\start-latest.ps1" %*
echo.
pause
