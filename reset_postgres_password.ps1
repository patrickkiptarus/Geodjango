$ErrorActionPreference = 'Stop'

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdmin) {
    throw 'This script must be run from PowerShell as Administrator so it can restart the PostgreSQL service.'
}

$serviceName = 'postgresql-x64-18'
$postgresBin = 'C:\Program Files\PostgreSQL\18\bin'
$dataDir = 'C:\Program Files\PostgreSQL\18\data'
$newPassword = Read-Host 'Enter the new postgres password'

if ([string]::IsNullOrWhiteSpace($newPassword)) {
    throw 'Password cannot be empty.'
}

$escapedPassword = $newPassword.Replace("'", "''")

$hba = Join-Path $dataDir 'pg_hba.conf'
$expectedHba = 'C:\Program Files\PostgreSQL\18\data\pg_hba.conf'
$resolvedHba = (Resolve-Path -LiteralPath $hba).Path

if ($resolvedHba -ne $expectedHba) {
    throw "Unexpected pg_hba.conf path: $resolvedHba"
}

$backup = "$hba.codex-reset-$(Get-Date -Format yyyyMMddHHmmss).bak"
Copy-Item -LiteralPath $hba -Destination $backup

$restored = $false

try {
    $original = Get-Content -LiteralPath $hba -Raw
    $temporaryAuth = @"
# Temporary local auth for password reset
host all all 127.0.0.1/32 trust
host all all ::1/128 trust
"@

    Set-Content -LiteralPath $hba -Value ($temporaryAuth + "`r`n" + $original) -Encoding ASCII
    Restart-Service -Name $serviceName -Force

    & (Join-Path $postgresBin 'psql.exe') `
        -h localhost `
        -p 5432 `
        -U postgres `
        -d postgres `
        -c "ALTER USER postgres WITH PASSWORD '$escapedPassword';"

    Copy-Item -LiteralPath $backup -Destination $hba -Force
    $restored = $true
    Restart-Service -Name $serviceName -Force

    $env:PGPASSWORD = $newPassword
    & (Join-Path $postgresBin 'psql.exe') `
        -h localhost `
        -p 5432 `
        -U postgres `
        -d postgres `
        -c 'SELECT current_user;'

    Write-Host "PostgreSQL password reset complete. Django .env is already set to POSTGRES_PASSWORD=$newPassword"
}
finally {
    if (-not $restored -and (Test-Path -LiteralPath $backup)) {
        Copy-Item -LiteralPath $backup -Destination $hba -Force
        Restart-Service -Name $serviceName -Force
    }
}
