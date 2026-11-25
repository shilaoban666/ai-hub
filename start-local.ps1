# AI Hub Core — Streamlined Local Startup (Backend + Frontend)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if (Test-Path "$Root\.venv\Scripts\python.exe") { "$Root\.venv\Scripts\python.exe" } else { "E:\Project\aihub\.venv\Scripts\python.exe" }

Write-Host "Starting AI Hub Core backend on http://127.0.0.1:15174 ..."
$Backend = Start-Process -FilePath $Python -ArgumentList "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "15174" -WorkingDirectory "$Root\backend" -PassThru

Write-Host "Starting AI Hub Core frontend on http://127.0.0.1:15173 ..."
$Frontend = Start-Process -FilePath "npm.cmd" -ArgumentList "run", "dev" -WorkingDirectory "$Root\frontend" -PassThru

Write-Host "Backend PID: $($Backend.Id), Frontend PID: $($Frontend.Id)"
Write-Host "Open http://localhost:15173 in your browser (default admin: admin / admin123)"
