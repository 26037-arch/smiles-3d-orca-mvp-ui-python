$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$backend = $null
$backendOwned = $false
$locationPushed = $false

function Get-ListenerProcess([int]$Port) {
    return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
}

function Test-GeoOrcaBackend {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        return $health.status -eq 'ok' -and $health.service -eq 'GeoORCA local backend'
    }
    catch { return $false }
}

function Test-GeoOrcaFrontend {
    try {
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:5173' -TimeoutSec 2 -UseBasicParsing
        return $page.StatusCode -eq 200 -and $page.Content -match 'GeoORCA'
    }
    catch { return $false }
}

$backendListener = Get-ListenerProcess 8000
$frontendListener = Get-ListenerProcess 5173
$backendReady = Test-GeoOrcaBackend
$frontendReady = Test-GeoOrcaFrontend

if ($backendListener -and -not $backendReady) {
    $process = Get-Process -Id $backendListener.OwningProcess -ErrorAction SilentlyContinue
    $name = if ($process) { $process.ProcessName } else { 'unknown' }
    throw "Port 8000 is already used by PID $($backendListener.OwningProcess) ($name), but it is not GeoORCA."
}
if ($frontendListener -and -not $frontendReady) {
    $process = Get-Process -Id $frontendListener.OwningProcess -ErrorAction SilentlyContinue
    $name = if ($process) { $process.ProcessName } else { 'unknown' }
    throw "Port 5173 is already used by PID $($frontendListener.OwningProcess) ($name), but it is not GeoORCA."
}
if ($backendReady -and $frontendReady) {
    Write-Host 'GeoORCA is already running.'
    Write-Host 'App: http://127.0.0.1:5173'
    Write-Host 'API: http://127.0.0.1:8000/docs'
    return
}

if (-not $backendReady) {
    $backend = Start-Process -FilePath 'python' -ArgumentList '-X', 'utf8', '-m', 'uvicorn', 'backend.app.main:app', '--host', '127.0.0.1', '--port', '8000', '--reload' -WorkingDirectory $root -PassThru -WindowStyle Hidden
    $backendOwned = $true
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        if ($backend.HasExited) { throw "Backend exited during startup (exit $($backend.ExitCode))." }
        if (Test-GeoOrcaBackend) { $backendReady = $true; break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $backendReady) { throw 'Backend was not ready within 10 seconds.' }
}
else {
    Write-Host 'Reusing the GeoORCA backend on port 8000.'
}

try {
    if ($frontendReady) {
        Write-Host 'GeoORCA is ready at http://127.0.0.1:5173'
        Write-Host 'The backend will remain running after this script exits.'
        $backendOwned = $false
        return
    }
    Push-Location (Join-Path $root 'frontend')
    $locationPushed = $true
    npm.cmd run dev
}
finally {
    if ($locationPushed) { Pop-Location }
    if ($backendOwned -and $backend -and -not $backend.HasExited) {
        # Uvicorn --reload owns a worker process; terminate only this server tree.
        & taskkill.exe /PID $backend.Id /T /F | Out-Null
    }
}
