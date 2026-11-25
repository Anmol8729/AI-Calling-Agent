# Clarivo Backend Startup Script
Set-Location -Path $PSScriptRoot
$env:PYTHONPATH = $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting Clarivo Backend API (Uvicorn)" -ForegroundColor Cyan
Write-Host "  URL: http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  API Docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
