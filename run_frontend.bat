@echo off
title Clarivo Frontend (Vite)
cd /d "%~dp0frontend"
echo ========================================
echo   Starting Clarivo Frontend (Vite)
echo   URL: http://127.0.0.1:5173
echo ========================================
call npm run dev
pause
