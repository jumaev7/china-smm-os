# Report who owns localhost:3000 (Docker vs local node.exe).
# Usage: .\scripts\check_frontend_port.ps1
# Exit codes: 0 = Docker-owned, 1 = node.exe-owned, 2 = free/other

$ErrorActionPreference = "Continue"

$DOCKER_NAMES = @(
    "com.docker.backend",
    "docker-proxy",
    "docker-desktop",
    "wslrelay",
    "vmwp"
)

function Get-Port3000Listeners {
    $listeners = @()

    try {
        $conns = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
            $listeners += [PSCustomObject]@{
                PID         = $conn.OwningProcess
                ProcessName = if ($proc) { $proc.ProcessName } else { "unknown" }
                Path        = if ($proc) { $proc.Path } else { $null }
                LocalAddr   = $conn.LocalAddress
            }
        }
    }
    catch {
        # Fallback when Get-NetTCPConnection is unavailable.
        $lines = netstat -ano | Select-String ":3000\s" | Select-String "LISTENING"
        foreach ($line in $lines) {
            $parts = ($line -replace "\s+", " ").Trim().Split(" ")
            $pid = [int]$parts[-1]
            if ($pid -eq 0) { continue }
            $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
            $listeners += [PSCustomObject]@{
                PID         = $pid
                ProcessName = if ($proc) { $proc.ProcessName } else { "unknown" }
                Path        = if ($proc) { $proc.Path } else { $null }
                LocalAddr   = $parts[1]
            }
        }
    }

    return $listeners | Sort-Object PID -Unique
}

$listeners = Get-Port3000Listeners

if (-not $listeners -or $listeners.Count -eq 0) {
    Write-Host "Port 3000: FREE (nothing listening)"
    exit 2
}

Write-Host "Port 3000 listeners:"
foreach ($l in $listeners) {
    $path = if ($l.Path) { " ($($l.Path))" } else { "" }
    Write-Host "  PID $($l.PID)  $($l.ProcessName)  $($l.LocalAddr)$path"
}

$hasNode = $false
$hasDocker = $false
foreach ($l in $listeners) {
    if ($l.ProcessName -eq "node") { $hasNode = $true }
    if ($DOCKER_NAMES -contains $l.ProcessName) { $hasDocker = $true }
}

if ($hasNode -and -not $hasDocker) {
    Write-Host "RESULT: node.exe owns port 3000 (local Next dev - conflicts with Docker frontend)"
    exit 1
}

if ($hasDocker -and -not $hasNode) {
    Write-Host "RESULT: Docker owns port 3000 (expected for dev)"
    exit 0
}

if ($hasDocker -and $hasNode) {
    Write-Host "RESULT: MIXED - both Docker and node.exe listen on port 3000 (run scripts/dev_frontend_reset.ps1)"
    exit 1
}

Write-Host "RESULT: port 3000 is in use by a non-Docker, non-node process"
exit 2
