$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = Start-Process -FilePath 'python' -ArgumentList '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload' -WorkingDirectory $root -PassThru -WindowStyle Hidden
try {
    Push-Location (Join-Path $root 'frontend')
    npm.cmd run dev
}
finally {
    Pop-Location
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id }
}

