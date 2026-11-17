# ZVEZDOCHKA Telegram v1.0.5 - self-contained Windows launcher.
# Windows PowerShell 5.1 / PowerShell 7; no system Python, py launcher or PATH required.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

Write-Host '============================================================'
Write-Host ' DZL ZVEZDOCHKA - TELEGRAM WINDOWS ONE CLICK v1.0.5'
Write-Host '============================================================'
Write-Host '[INFO] Isolated Python 3.12 setup. Windows PATH is not required.'

# Fixed, SHA-256-verified official Astral uv v0.13.8 Windows x64 release.
# https://github.com/astral-sh/uv/releases/tag/0.13.8
$uvVersion = '0.13.8'
$uvSha256 = '529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8'
$uvUrl = 'https://github.com/astral-sh/uv/releases/download/0.13.8/uv-x86_64-pc-windows-msvc.zip'
$uvDir = Join-Path $root '.tools\uv'
$uvExe = Join-Path $uvDir 'uv.exe'
$venvDir = Join-Path $root '.venv'
$venvExe = Join-Path $venvDir 'Scripts\python.exe'

function Assert-Success([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw ("$Step failed (exit code $LASTEXITCODE). See the error output above.")
    }
}

function Test-LocalPython {
    if (-not (Test-Path -LiteralPath $venvExe -PathType Leaf)) { return $false }
    try {
        & $venvExe -c 'import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 3)' 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Ensure-Uv {
    if (Test-Path -LiteralPath $uvExe -PathType Leaf) {
        try {
            & $uvExe --version | Out-Null
            if ($LASTEXITCODE -eq 0) { return }
        } catch { }
        Remove-Item -LiteralPath $uvExe -Force -ErrorAction SilentlyContinue
    }

    if (([Environment]::Is64BitOperatingSystem -ne $true) -or
        (([string]$env:PROCESSOR_ARCHITECTURE -notmatch 'AMD64') -and
         ([string]$env:PROCESSOR_ARCHITEW6432 -notmatch 'AMD64'))) {
        throw 'This one-click build requires x64 Windows 10/11. Please send us your Windows architecture.'
    }

    Write-Host ('[1/5] Downloading verified uv ' + $uvVersion + ' (one time)...')
    New-Item -ItemType Directory -Path $uvDir -Force | Out-Null
    $zipFile = Join-Path $uvDir 'uv-download.zip'
    $extractDir = Join-Path $uvDir '_extract'
    Remove-Item -LiteralPath $zipFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue
    try {
        # TLS 1.2 is required for GitHub downloads on older Windows setups.
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -UseBasicParsing -Uri $uvUrl -OutFile $zipFile -TimeoutSec 180
        $actualSha = (Get-FileHash -LiteralPath $zipFile -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -ne $uvSha256) {
            throw 'SHA-256 verification FAILED: the downloaded uv executable does not match the official release.'
        }
        Expand-Archive -LiteralPath $zipFile -DestinationPath $extractDir -Force
        $found = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter 'uv.exe' -File | Select-Object -First 1
        if (-not $found) { throw 'uv.exe is missing from the verified archive.' }
        Copy-Item -LiteralPath $found.FullName -Destination $uvExe -Force
        & $uvExe --version
        Assert-Success 'uv validation'
    } catch {
        throw ('Failed to download/run uv. Check internet access to GitHub (no Python reinstall is needed). Details: ' + $_.Exception.Message)
    } finally {
        Remove-Item -LiteralPath $zipFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $extractDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    if (Test-LocalPython) {
        Write-Host '[1/5] Existing Python 3.12 environment found. Reusing it.'
    } else {
        Ensure-Uv
        if (Test-Path -LiteralPath $venvDir) {
            $backupDir = Join-Path $root ('.venv_old_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
            Move-Item -LiteralPath $venvDir -Destination $backupDir
            Write-Host ('[INFO] Old/broken environment saved in: ' + $backupDir)
        }
        Write-Host '[2/5] Installing an isolated Python 3.12 and creating environment...'
        & $uvExe venv --python 3.12 --managed-python --seed $venvDir
        Assert-Success 'uv venv'
        if (-not (Test-LocalPython)) { throw 'New Python 3.12 environment did not pass the version check.' }
    }

    # uv installs dependencies without needing python, pip or py to be on PATH.
    Ensure-Uv
    Write-Host '[3/5] Installing/updating Python dependencies...'
    & $uvExe pip install --python $venvExe -r (Join-Path $root 'requirements.txt')
    Assert-Success 'uv pip install'

    $envPath = Join-Path $root '.env'
    if (-not (Test-Path -LiteralPath $envPath)) {
        Copy-Item -LiteralPath (Join-Path $root '.env.example') -Destination $envPath
    }
    $existing = Get-Content -LiteralPath $envPath -Raw -Encoding UTF8
    if ($existing -notmatch '(?m)^TELEGRAM_BOT_TOKEN=\d+:[A-Za-z0-9_-]+\s*$') {
        Write-Host '[4/5] Enter your Telegram token from @BotFather (hidden input):'
        $secret = Read-Host 'Paste token' -AsSecureString
        $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
        try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
        if ($token -notmatch '^\d+:[A-Za-z0-9_-]+$') { throw 'Invalid bot token format. Recheck it in @BotFather.' }
        if ($existing -match '(?m)^TELEGRAM_BOT_TOKEN=') {
            $existing = [regex]::Replace($existing, '(?m)^TELEGRAM_BOT_TOKEN=.*$', "TELEGRAM_BOT_TOKEN=$token")
        } else {
            $existing += "`nTELEGRAM_BOT_TOKEN=$token`n"
        }
        [System.IO.File]::WriteAllText($envPath, $existing, (New-Object System.Text.UTF8Encoding($false)))
        $token = $null
        Write-Host '[OK] Token saved to local .env only (do not share or push this file).'
    } else {
        Write-Host '[4/5] Existing Telegram token found. Keeping it unchanged.'
    }

    Write-Host '[5/5] Starting bot... Ctrl+C to stop.'
    & $venvExe -m app.main
    Assert-Success 'Telegram bot'
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
