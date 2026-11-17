#Requires -Version 5.1
# Optional owner setup; never assigns ownership to the first visitor automatically.
$ErrorActionPreference = 'Stop'
try {
    $root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
    $envPath = Join-Path $root '.env'
    if (-not (Test-Path -LiteralPath $envPath)) { throw 'Сначала запустите START_TOURIST.bat и введите токен.' }
    Write-Host 'Откройте бота в Telegram и отправьте /id. Скопируйте число из ответа.'
    $owner = (Read-Host 'Ваш числовой Telegram ID').Trim()
    if ($owner -notmatch '^[1-9][0-9]{0,15}$') { throw 'Нужен положительный Telegram ID (только цифры).' }
    $body = [System.IO.File]::ReadAllText($envPath)
    $rx = '(?m)^\s*OWNER_TELEGRAM_ID\s*=[^\r\n]*'
    if ([regex]::IsMatch($body, $rx)) {
        $body = [regex]::Replace($body, $rx, 'OWNER_TELEGRAM_ID=' + $owner)
    } else {
        $body += "`r`nOWNER_TELEGRAM_ID=" + $owner + "`r`n"
    }
    [System.IO.File]::WriteAllText($envPath, $body, ([System.Text.UTF8Encoding]::new($false)))
    Write-Host '[OK] ID владельца сохранён в .env. Закройте окно бота (Ctrl+C) и снова запустите START_TOURIST.bat.'
    exit 0
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
