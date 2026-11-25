# Clarivo Frontend Startup Script
Set-Location -Path "$PSScriptRoot\frontend"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Starting Clarivo Frontend (Vite)" -ForegroundColor Cyan
Write-Host "  URL: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan

npm run dev
