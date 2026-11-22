@echo off
title Clarivo AI Voice Platform - Unified Server
cd /d "%~dp0"
echo ==========================================================
echo    Clarivo Voice AI Platform - All-in-One Unified Server   
echo ==========================================================
echo.
echo  App URL: http://localhost:8000
echo  Login  : demo@clarivo.io / password123
echo.
powershell -ExecutionPolicy Bypass -File "%~dp0run_all.ps1"
pause
