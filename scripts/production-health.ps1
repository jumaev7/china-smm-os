param(
    [string]$EnvFile = ".env.production",
    [string]$ComposeFile = "docker-compose.production.yml"
)

$ErrorActionPreference = "Stop"
$compose = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile)
$requiredServices = @(
    "postgres",
    "backend",
    "frontend",
    "automation-worker",
    "telegram-webhook-worker",
    "listening-worker",
    "publish-alert-telegram-worker",
    "cloudflared"
)

$json = & docker @compose ps --format json | ConvertFrom-Json
$rows = foreach ($service in $requiredServices) {
    $container = @($json | Where-Object { $_.Service -eq $service }) | Select-Object -First 1
    [pscustomobject]@{
        Service = $service
        State = if ($container) { $container.State } else { "missing" }
        Health = if ($container.Health) { $container.Health } else { "n/a" }
    }
}

$bad = @($rows | Where-Object { $_.State -ne "running" -or $_.Health -eq "unhealthy" })

$publicChecks = foreach ($url in @(
    "https://api.chinasmmos.com/health",
    "https://app.chinasmmos.com/login"
)) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 15
        [pscustomobject]@{ URL = $url; Status = $response.StatusCode; OK = $response.StatusCode -eq 200 }
    }
    catch {
        [pscustomobject]@{ URL = $url; Status = "error"; OK = $false }
    }
}

$apex = & curl.exe -sS -o NUL -w "%{http_code} %{redirect_url}" --max-time 20 https://chinasmmos.com/
$db = & docker @compose exec -T postgres psql -U postgres -d china_smm_os -Atc `
    "SELECT current_database() || '|' || (SELECT count(*) FROM clients) || '|' || (SELECT count(*) FROM content_items);"

$rows | Format-Table -AutoSize
$publicChecks | Format-Table -AutoSize
Write-Output "Apex: $apex"
Write-Output "Database|clients|content_items: $db"

if ($bad.Count -gt 0 -or @($publicChecks | Where-Object { -not $_.OK }).Count -gt 0) {
    throw "Production health check failed"
}

Write-Output "PRODUCTION HEALTH: PASS"
