param(
    [string]$Source = "backend/.env",
    [string]$Target = ".env.production"
)

$ErrorActionPreference = "Stop"

function Read-DotEnv([string]$Path) {
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $values[$matches[1]] = $matches[2]
        }
    }
    return $values
}

function Require-Value($Values, [string]$Name) {
    $value = [string]$Values[$Name]
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required source value is missing: $Name"
    }
    return $value
}

function New-UrlSafeSecret([int]$Bytes = 48) {
    $buffer = New-Object byte[] $Bytes
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    }
    finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($buffer).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

$sourceValues = Read-DotEnv $Source
$postgresPassword = New-UrlSafeSecret 36
$values = [ordered]@{
    POSTGRES_DB = "china_smm_os"
    POSTGRES_USER = "postgres"
    POSTGRES_PASSWORD = $postgresPassword
    DATABASE_URL = "postgresql+asyncpg://postgres:${postgresPassword}@postgres:5432/china_smm_os"
    APP_ENV = "production"
    DEMO_MODE = "false"
    SECRET_KEY = New-UrlSafeSecret
    ADMIN_SECRET_KEY = New-UrlSafeSecret
    TENANT_SECRET_KEY = New-UrlSafeSecret
    ADMIN_BOOTSTRAP_EMAIL = ""
    ADMIN_BOOTSTRAP_PASSWORD = ""
    PUBLIC_APP_URL = "https://app.chinasmmos.com"
    CORS_ORIGINS = "https://app.chinasmmos.com,https://chinasmmos.com"
    NEXT_PUBLIC_API_URL = "https://api.chinasmmos.com/api/v1"
    MEDIA_BASE_URL = "https://api.chinasmmos.com"
    USE_S3 = "true"
    S3_BUCKET = Require-Value $sourceValues "S3_BUCKET"
    S3_ENDPOINT_URL = Require-Value $sourceValues "S3_ENDPOINT_URL"
    S3_PUBLIC_BASE_URL = Require-Value $sourceValues "S3_PUBLIC_BASE_URL"
    S3_ACCESS_KEY = Require-Value $sourceValues "S3_ACCESS_KEY"
    S3_SECRET_KEY = Require-Value $sourceValues "S3_SECRET_KEY"
    OPENAI_API_KEY = Require-Value $sourceValues "OPENAI_API_KEY"
    OPENAI_MODEL = $(if ($sourceValues["OPENAI_MODEL"]) { $sourceValues["OPENAI_MODEL"] } else { "gpt-4o" })
    TELEGRAM_BOT_TOKEN = Require-Value $sourceValues "TELEGRAM_BOT_TOKEN"
    TELEGRAM_ADMIN_ID = Require-Value $sourceValues "TELEGRAM_ADMIN_ID"
    TELEGRAM_WEBHOOK_SECRET = New-UrlSafeSecret
    META_APP_ID = Require-Value $sourceValues "META_APP_ID"
    META_APP_SECRET = Require-Value $sourceValues "META_APP_SECRET"
    META_OAUTH_REDIRECT_URI = "https://api.chinasmmos.com/api/v1/publishing/meta/oauth/callback"
    LISTENING_META_WEBHOOK_VERIFY_TOKEN = New-UrlSafeSecret
    TUNNEL_TOKEN = Require-Value $sourceValues "TUNNEL_TOKEN"
    ENABLE_FACEBOOK_LIVE_SMOKE = "false"
    ENABLE_INSTAGRAM_LIVE_SMOKE = "false"
    SCHEDULED_PUBLISH_ENABLED = "true"
}

$lines = foreach ($entry in $values.GetEnumerator()) {
    "$($entry.Key)=$($entry.Value)"
}
[System.IO.File]::WriteAllLines(
    (Join-Path (Get-Location) $Target),
    $lines,
    [System.Text.UTF8Encoding]::new($false)
)

Write-Output "Production environment created: $Target"
Write-Output "Configured keys: $($values.Count); secrets were not printed"
