# Clarivo All-in-One Startup Script
Set-Location -Path $PSScriptRoot
$env:PYTHONPATH = $PSScriptRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   Clarivo Voice AI Platform - All-in-One Unified Server   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " [✓] Unified App URL  : http://localhost:8000" -ForegroundColor Green
Write-Host " [✓] Dashboard URL    : http://localhost:8000/dashboard" -ForegroundColor Green
Write-Host " [✓] Interactive Docs : http://localhost:8000/docs" -ForegroundColor Green
Write-Host " [✓] Demo Account     : demo@clarivo.io / password123" -ForegroundColor Yellow
Write-Host ""
Write-Host "Building latest frontend assets if needed..." -ForegroundColor Gray
npm --prefix frontend run build

Write-Host ""
Write-Host "Starting Unified FastAPI Server on port 8000..." -ForegroundColor Cyan
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
