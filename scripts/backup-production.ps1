param(
    [string]$EnvFile = ".env.production",
    [string]$ComposeFile = "docker-compose.production.yml",
    [string]$BackupDirectory = "backups"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$compose = @("compose", "--env-file", $EnvFile, "-f", $ComposeFile)
$container = (& docker @compose ps -q postgres).Trim()
if (-not $container) {
    throw "Production PostgreSQL container is not running"
}

$resolvedBackupDirectory = Join-Path (Get-Location) $BackupDirectory
New-Item -ItemType Directory -Force -Path $resolvedBackupDirectory | Out-Null
$name = "production-$stamp.dump"
$containerPath = "/tmp/$name"
$hostPath = Join-Path $resolvedBackupDirectory $name

& docker @compose exec -T postgres pg_dump -Fc -U postgres -d china_smm_os -f $containerPath
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }

& docker cp "${container}:$containerPath" $hostPath
if ($LASTEXITCODE -ne 0) { throw "docker cp failed" }

& docker @compose exec -T postgres pg_restore -l $containerPath | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pg_restore archive validation failed" }

$file = Get-Item -LiteralPath $hostPath
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $hostPath
Write-Output "Production backup verified"
Write-Output "Path: $($file.FullName)"
Write-Output "Bytes: $($file.Length)"
Write-Output "SHA256: $($hash.Hash)"
