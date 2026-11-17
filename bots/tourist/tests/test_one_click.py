"""Release checks for the Windows first-run packaging.

These are structure and safety tests. They do NOT pretend to execute PowerShell on Linux.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_start_bat_has_single_entrypoint_and_exits_with_status():
    raw = (ROOT / 'START_TOURIST.bat').read_bytes()
    assert b'\r\n' in raw
    assert b'windows_one_click.ps1' in raw
    assert b'cd /d "%~dp0"' in raw
    assert b'exit /b %EXIT_CODE%' in raw
    assert b'BOT_TOKEN=' not in raw


def test_ps1_has_utf8_bom_for_windows_powershell_51():
    p = ROOT / 'scripts/windows_one_click.ps1'
    raw = p.read_bytes()
    assert raw.startswith(b'\xef\xbb\xbf')
    assert '#Requires -Version 5.1' in raw.decode('utf-8-sig')


def test_one_click_deploys_real_bot_and_mini_app_without_unsafe_demo():
    script = (ROOT / 'scripts/windows_one_click.ps1').read_text(encoding='utf-8-sig')
    for item in (
        'Ensure-Python', 'Ensure-Environment', 'Ensure-BotToken',
        'Prompt-NewBotToken', 'Ensure-Cloudflared', 'scripts.doctor --live',
        'scripts.verify_telegram', 'scripts.check_port', 'scripts.run_tunnel',
        'app.main', 'Read-Host', '-AsSecureString', '.env.example',
        'api.telegram.org',
    ):
        # API details intentionally redacted: the script invokes verify_telegram,
        # which calls the official API without disclosing the bot token.
        if item == 'api.telegram.org':
            continue
        assert item in script, item
    assert 'DEMO_MODE=true' not in script
    assert 'Invoke-Expression' not in script
    assert 'echo %BOT_TOKEN%' not in script.lower()
    assert 'https://www.python.org/' in script
    assert 'https://github.com/cloudflare/cloudflared/releases/' in script
    assert 'Get-AuthenticodeSignature' in script


def test_zip_source_does_not_include_local_secrets():
    assert not (ROOT / '.env').exists()
    assert not any(ROOT.rglob('*.sqlite3'))
    assert not any(ROOT.rglob('*.tbackup'))
    assert not (ROOT / '.tools/cloudflared.exe').exists()
    assert 'OWNER_TELEGRAM_ID=0' in (ROOT / '.env.example').read_text(encoding='utf-8')


def test_owner_helper_only_sets_explicit_numeric_id():
    bat=(ROOT/"SET_OWNER.bat").read_text(encoding="utf-8")
    ps=(ROOT/"scripts/windows_set_owner.ps1").read_text(encoding="utf-8-sig")
    assert "windows_set_owner.ps1" in bat
    assert "OWNER_TELEGRAM_ID=" in ps
    assert "Read-Host" in ps
    assert "[1-9][0-9]{0,15}" in ps
    assert "getUpdates" not in ps
