#Requires -Version 5.1
# TOURIST single-click bootstrap, Windows 10/11 x64.
# The only mandatory secret is supplied interactively; do not pass bot tokens in CLI arguments.
# Encoding: UTF-8 with BOM for Windows PowerShell 5.1.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Project = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $Project
$VenvPython = Join-Path $Project '.venv\Scripts\python.exe'
$ToolDir = Join-Path $Project '.tools'
$Cloudflared = Join-Path $ToolDir 'cloudflared.exe'
$EnvFile = Join-Path $Project '.env'
$ExampleEnv = Join-Path $Project '.env.example'
$Utf8 = [System.Text.UTF8Encoding]::new($false)
$PythonInstallerUrl = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
$CloudflaredUrl = 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe'

function Say([string] $message) { Write-Host ('[TOURIST] ' + $message) }
function Warn([string] $message) { Write-Host ('[WARNING] ' + $message) -ForegroundColor Yellow }
function Abort([string] $message) { throw $message }

function Locate-Python {
    $items = New-Object System.Collections.ArrayList
    if (Get-Command 'py.exe' -ErrorAction SilentlyContinue) {
        foreach ($v in @('-3.12','-3.13','-3.11')) {
            [void] $items.Add([pscustomobject]@{ Exe = 'py.exe'; Prefix = @($v) })
        }
    }
    $local = [Environment]::GetFolderPath('LocalApplicationData')
    foreach ($p in @(
        (Join-Path $local 'Programs\Python\Python312\python.exe'),
        (Join-Path $local 'Programs\Python\Python313\python.exe'),
        (Join-Path $local 'Programs\Python\Python311\python.exe'),
        'C:\Program Files\Python312\python.exe',
        'C:\Program Files\Python313\python.exe',
        'C:\Program Files\Python311\python.exe'
    )) {
        if (Test-Path -LiteralPath $p -PathType Leaf) {
            [void] $items.Add([pscustomobject]@{ Exe = $p; Prefix = @() })
        }
    }
    if (Get-Command 'python.exe' -ErrorAction SilentlyContinue) {
        [void] $items.Add([pscustomobject]@{ Exe = 'python.exe'; Prefix = @() })
    }
    foreach ($item in $items) {
        $prefix = @($item.Prefix)
        try {
            & $item.Exe @prefix -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,13); assert sys.maxsize > 2**32; import venv, ensurepip" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $item }
        } catch { }
    }
    return $null
}

function Download-Official([string] $url, [string] $target) {
    Say 'Скачиваю необходимый компонент с официального сайта...'
    $tmp = $target + '.download'
    if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing -TimeoutSec 240 -MaximumRedirection 8
        if ((Get-Item -LiteralPath $tmp).Length -lt 2000000) { Abort 'Загружен слишком маленький или повреждённый файл.' }
        Move-Item -LiteralPath $tmp -Destination $target -Force
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force }
    }
}

function Ensure-Python {
    $candidate = Locate-Python
    if ($null -ne $candidate) {
        Say ('Найден совместимый Python: ' + $candidate.Exe + ' ' + ($candidate.Prefix -join ' '))
        return $candidate
    }
    Say 'Python 3.11–3.13 x64 не найден. Установлю Python 3.12.10 для текущего пользователя.'
    Say 'Администраторские права не нужны; это одноразовая операция.'
    if (-not [Environment]::Is64BitOperatingSystem) { Abort 'Нужна 64-разрядная Windows 10/11.' }
    if (-not (Test-Path -LiteralPath $ToolDir)) { New-Item -ItemType Directory -Path $ToolDir | Out-Null }
    $installer = Join-Path $ToolDir 'python-3.12.10-amd64.exe'
    Download-Official $PythonInstallerUrl $installer
    $sig = Get-AuthenticodeSignature -LiteralPath $installer
    if ($sig.Status -ne 'Valid') { Remove-Item -LiteralPath $installer -Force; Abort 'Установщик Python не прошёл проверку цифровой подписи.' }
    Say 'Подпись Python подтверждена. Выполняю установку...'
    $argsList = '/quiet InstallAllUsers=0 PrependPath=0 Include_pip=1 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0'
    $proc = Start-Process -FilePath $installer -ArgumentList $argsList -PassThru -Wait
    if (Test-Path -LiteralPath $installer) { Remove-Item -LiteralPath $installer -Force }
    if ($proc.ExitCode -ne 0) { Abort ('Установка Python завершилась с кодом ' + $proc.ExitCode + '. Попробуйте установку Python 3.12 x64 с python.org вручную.') }
    $candidate = Locate-Python
    if ($null -eq $candidate) { Abort 'Python установился, но программа не смогла его найти. Перезагрузите Windows и запустите BAT повторно.' }
    return $candidate
}

function Ensure-Environment($basePython) {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Say 'Создаю локальное Python-окружение .venv...'
        $prefix = @($basePython.Prefix)
        & $basePython.Exe @prefix -m venv (Join-Path $Project '.venv')
        if ($LASTEXITCODE -ne 0) { Abort 'Не удалось создать .venv. Проверьте свободное место на диске.' }
    }
    $requirements = Join-Path $Project 'requirements.txt'
    $checksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirements).Hash
    $stamp = Join-Path $Project '.venv\tourist-requirements.sha256'
    $needed = $true
    if (Test-Path -LiteralPath $stamp) {
        $existing = (Get-Content -LiteralPath $stamp -Raw).Trim()
        if ($existing -eq $checksum) {
            & $VenvPython -c 'import aiogram, fastapi, uvicorn, httpx, pydantic, cryptography, tzdata, gspread, boto3, dotenv' 2>$null
            if ($LASTEXITCODE -eq 0) { $needed = $false }
        }
    }
    if ($needed) {
        Say 'Устанавливаю библиотеки проекта. В первый запуск нужен интернет...'
        & $VenvPython -m pip install --disable-pip-version-check --prefer-binary -r $requirements
        if ($LASTEXITCODE -ne 0) { Abort 'Установка библиотек не удалась. Проверьте интернет, VPN, антивирус и свободное место, затем запустите BAT повторно.' }
        [System.IO.File]::WriteAllText($stamp, $checksum + "`n", $Utf8)
    } else {
        Say 'Все библиотеки установлены; повторная загрузка не требуется.'
    }
}

function Read-EnvToken {
    if (-not (Test-Path -LiteralPath $EnvFile)) { return '' }
    $body = [System.IO.File]::ReadAllText($EnvFile)
    $m = [regex]::Match($body, '(?m)^\s*BOT_TOKEN\s*=\s*([^\r\n]*)')
    if (-not $m.Success) { return '' }
    return $m.Groups[1].Value.Trim().Trim('"').Trim("'")
}

function Set-EnvToken([string] $token) {
    if ($token -notmatch '^\d{5,}:[A-Za-z0-9_-]{20,}$') { Abort 'Неверный формат токена.' }
    $body = [System.IO.File]::ReadAllText($EnvFile)
    $line = 'BOT_TOKEN=' + $token
    if ([regex]::IsMatch($body, '(?m)^\s*BOT_TOKEN\s*=')) {
        $body = [regex]::Replace($body, '(?m)^\s*BOT_TOKEN\s*=[^\r\n]*', $line)
    } else {
        $body = $line + "`r`n" + $body
    }
    [System.IO.File]::WriteAllText($EnvFile, $body, $Utf8)
}

function Prompt-NewBotToken {
    Say 'Введите токен Telegram-бота, полученный у @BotFather.'
    Say 'Символы не отображаются; токен сохранится только в локальном .env.'
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        $secure = Read-Host 'BOT_TOKEN (вставьте и нажмите Enter)' -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
        $token = $token.Trim()
        if ($token -match '^\d{5,}:[A-Za-z0-9_-]{20,}$') {
            Set-EnvToken $token
            Say 'Токен записан. В окно запуска не выводится.'
            return
        }
        Warn 'Токен не похож на токен BotFather. Попробуйте скопировать его полностью.'
    }
    Abort 'Слишком много неверных попыток ввода токена.'
}

function Ensure-BotToken {
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        if (-not (Test-Path -LiteralPath $ExampleEnv)) { Abort 'Не найден .env.example: распакуйте ZIP целиком.' }
        Copy-Item -LiteralPath $ExampleEnv -Destination $EnvFile
    }
    # Only initialize this optional mode if the user has not configured it.
    $body = [System.IO.File]::ReadAllText($EnvFile)
    if (-not [regex]::IsMatch($body, '(?m)^\s*SHOWCASE_MODE\s*=')) {
        [System.IO.File]::AppendAllText($EnvFile, "`r`nSHOWCASE_MODE=true`r`n", $Utf8)
    }
    $token = Read-EnvToken
    if ($token -match '^\d{5,}:[A-Za-z0-9_-]{20,}$') {
        Say 'Токен найден в .env; вводить повторно не нужно.'
        return
    }
    Prompt-NewBotToken
}

function Ensure-Cloudflared {
    if (-not (Test-Path -LiteralPath $ToolDir)) { New-Item -ItemType Directory -Path $ToolDir | Out-Null }
    if (Test-Path -LiteralPath $Cloudflared -PathType Leaf) {
        try {
            & $Cloudflared --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { Say 'Cloudflare Tunnel уже установлен.'; return $true }
        } catch { }
        Remove-Item -LiteralPath $Cloudflared -Force
    }
    try {
        Say 'Подготавливаю HTTPS для Telegram Mini App (Cloudflare Quick Tunnel)...'
        Download-Official $CloudflaredUrl $Cloudflared
        & $Cloudflared --version 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { Abort 'Cloudflared не запускается на этом компьютере.' }
        Say 'Cloudflare Tunnel установлен.'
        return $true
    } catch {
        Warn 'Не удалось установить Cloudflare Tunnel: Mini App внутри Telegram пока недоступна.'
        Warn 'Возможны ограничения GitHub/VPN/антивируса. Текстовый бот всё равно запустится.'
        return $false
    }
}

try {
    Say 'Проверяю Python и готовлю приложение...'
    $basePython = Ensure-Python
    Ensure-Environment $basePython
    Ensure-BotToken
    Say 'Проверяю конфигурацию, свободный порт и связь с Telegram Bot API...'
    & $VenvPython -m scripts.doctor --live
    if ($LASTEXITCODE -ne 0) { Abort 'Проверка настроек не пройдена. Посмотрите сообщения выше.' }
    & $VenvPython -m scripts.check_port
    if ($LASTEXITCODE -ne 0) { Abort 'Порт 8000 занят. Закройте другую копию бота или использующую порт программу.' }
    $verified = $false
    for ($check = 1; $check -le 3; $check++) {
        & $VenvPython -m scripts.verify_telegram
        if ($LASTEXITCODE -eq 0) { $verified = $true; break }
        if ($check -lt 3) {
            Warn 'Проверка Telegram не прошла. Возможны неверный токен, VPN или старый webhook.'
            $choice = Read-Host 'Чтобы ввести другой токен, напишите TOKEN; чтобы проверить сеть ещё раз, нажмите Enter'
            if ($choice.Trim().ToUpperInvariant() -eq 'TOKEN') { Prompt-NewBotToken }
        }
    }
    if (-not $verified) { Abort 'Telegram не подтвердил токен или обнаружен активный webhook. Посмотрите сообщения выше.' }

    $hasTunnel = Ensure-Cloudflared
    Write-Host ''
    Say 'УСТАНОВКА ГОТОВА. Окно должно оставаться открытым, пока работает бот.'
    Say 'В Telegram отправьте боту /start. Для открытия сайта — кнопку Mini App.'
    Say 'Локальный сайт: http://127.0.0.1:8000 (без Telegram-авторизации действия недоступны).'
    Say 'Чтобы узнать ID владельца, отправьте боту /id и впишите его в OWNER_TELEGRAM_ID в .env; затем перезапустите BAT.'
    Write-Host ''

    if ($hasTunnel) {
        Say 'Запускаю Telegram-бот и Mini App через HTTPS...'
        & $VenvPython -m scripts.run_tunnel
        $tunnelExit = $LASTEXITCODE
        if ($tunnelExit -eq 0) { exit 0 }
        Warn 'Mini App через HTTPS не удалось запустить или туннель отключился.'
        Warn 'Пытаюсь запустить Telegram-бот без внешней Mini App...'
    }
    Say 'Запускаю обычный Telegram-бот и локальный сайт...'
    & $VenvPython -m app.main
    exit $LASTEXITCODE
} catch {
    # Intentionally never print raw exceptions: network exception details may contain secret URLs.
    $message = [string]$_.Exception.Message
    if ($message -match 'BOT_TOKEN=|api.telegram.org/bot|\d{5,}:[A-Za-z0-9_-]{20,}') {
        $message = 'Ошибка подключения или неверный токен. Не публикуйте содержимое .env.'
    }
    Write-Host ('[ERROR] ' + $message) -ForegroundColor Red
    Write-Host 'Исправьте проблему и снова откройте START_TOURIST.bat. Настройки и база сохраняются.'
    exit 1
}
