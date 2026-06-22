# Reset the frontend dev environment: free port 3000, remove host .next, recreate Docker frontend.
# Usage: .\scripts\dev_frontend_reset.ps1
# Requires: Docker Desktop running, Python 3 on PATH.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "==> Frontend dev reset (repo: $RepoRoot)"

# 1. Stop local node.exe processes listening on port 3000.
Write-Host "`n==> Checking port 3000 for local node.exe..."
$stopped = 0
try {
    $conns = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq "node") {
            Write-Host "    Stopping node.exe PID $($proc.Id) on port 3000"
            Stop-Process -Id $proc.Id -Force
            $stopped++
        }
    }
}
catch {
    $lines = netstat -ano | Select-String ":3000\s" | Select-String "LISTENING"
    foreach ($line in $lines) {
        $parts = ($line -replace "\s+", " ").Trim().Split(" ")
        $pid = [int]$parts[-1]
        if ($pid -eq 0) { continue }
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc -and $proc.ProcessName -eq "node") {
            Write-Host "    Stopping node.exe PID $($proc.Id) on port 3000"
            Stop-Process -Id $proc.Id -Force
            $stopped++
        }
    }
}
if ($stopped -eq 0) {
    Write-Host "    No node.exe listener on port 3000"
}

# 2. Remove host frontend/.next (polluted by local npm run dev/build).
$hostNext = Join-Path $RepoRoot "frontend\.next"
if (Test-Path $hostNext) {
    Write-Host "`n==> Removing host frontend/.next ..."
    Remove-Item -Recurse -Force $hostNext
    Write-Host "    Removed $hostNext"
}
else {
    Write-Host "`n==> Host frontend/.next not present (OK)"
}

# 3. Recreate Docker frontend container (named volume keeps container .next isolated).
Write-Host "`n==> Recreating Docker frontend ..."
docker compose up -d --force-recreate --no-deps frontend
if ($LASTEXITCODE -ne 0) {
    Write-Error "docker compose up failed (exit $LASTEXITCODE). Is Docker Desktop running?"
}

# 4. Wait until /dashboard responds.
Write-Host "`n==> Waiting for frontend (up to 120s) ..."
$ready = $false
for ($i = 1; $i -le 24; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:3000/dashboard" -UseBasicParsing -TimeoutSec 5
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            Write-Host "    Frontend ready after $($i * 5)s (HTTP 200 /dashboard)"
            break
        }
    }
    catch {
        Write-Host "    ... waiting ($($i * 5)s)"
        Start-Sleep -Seconds 5
    }
}
if (-not $ready) {
    Write-Error "Frontend did not become ready within 120s. Check: docker compose logs frontend"
}

# 5. Verify CSS/JS assets.
Write-Host "`n==> Verifying CSS/JS assets ..."
python (Join-Path $RepoRoot "scripts\verify_frontend_css.py")
$verifyExit = $LASTEXITCODE
if ($verifyExit -ne 0) {
    Write-Error "verify_frontend_css.py failed (exit $verifyExit)"
}

Write-Host "`n==> Frontend dev reset complete."
exit 0
