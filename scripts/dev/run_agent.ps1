Set-Location -Path "$PSScriptRoot\agent"
if (Test-Path "$PSScriptRoot\agent\.venv\Scripts\python.exe") {
    & "$PSScriptRoot\agent\.venv\Scripts\python.exe" main.py dev
} else {
    & "$PSScriptRoot\.venv\Scripts\python.exe" main.py dev
}

