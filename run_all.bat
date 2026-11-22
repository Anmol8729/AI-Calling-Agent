@echo off
title Clarivo Platform Launcher
echo ========================================
echo   Launching Clarivo Platform
echo ========================================
echo 1. Starting Backend API on http://127.0.0.1:8000 ...
start "Clarivo Backend" cmd /k "%~dp0run_backend.bat"
timeout /t 2 /nobreak >nul
echo 2. Starting Frontend on http://127.0.0.1:5173 ...
start "Clarivo Frontend" cmd /k "%~dp0run_frontend.bat"
echo ========================================
echo   Both services started in separate windows!
echo   Frontend: http://127.0.0.1:5173
echo   Backend:  http://127.0.0.1:8000
echo ========================================
timeout /t 5
