"""Start a temporary HTTPS Cloudflare Quick Tunnel + Tourist bot on Windows.

cloudflared is installed manually from Cloudflare's official website.
This is for development only. Never publish DEMO_MODE.
"""
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from app.config import ROOT, settings
from app.runtime import assert_port_free, StartupError

URL_PATTERN = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com', re.IGNORECASE)


def locate_cloudflared():
    bundled = ROOT / '.tools' / ('cloudflared.exe' if os.name == 'nt' else 'cloudflared')
    if bundled.is_file():
        return str(bundled)
    return shutil.which('cloudflared')


def start_tunnel(exe, seconds=60):
    """Obtain temporary HTTPS URL without leaking a process on failure/interrupt."""
    process = subprocess.Popen([exe, 'tunnel', '--url', 'http://127.0.0.1:8000'],
                               cwd=str(ROOT), stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding='utf-8', errors='replace', bufsize=1)
    messages = queue.Queue(maxsize=100)

    def read_output():
        # Cloudflared stays running for hours. Do not leak RAM accumulating logs.
        for line in process.stdout:
            try:
                messages.put_nowait(line.strip())
            except queue.Full:
                pass

    threading.Thread(target=read_output, daemon=True).start()
    healthy = False
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                line = messages.get(timeout=0.5)
                match = URL_PATTERN.search(line)
                if match and process.poll() is None:
                    healthy = True
                    return process, match.group(0)
                if 'error' in line.lower() or 'failed' in line.lower():
                    print('[Tunnel] ' + line[:450], flush=True)
            except queue.Empty:
                pass
            if process.poll() is not None:
                break
        raise RuntimeError('Не удалось получить временную HTTPS-ссылку. Проверьте интернет, VPN и cloudflared.')
    finally:
        if not healthy and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def wait_for_our_api(bot_process, expected_version=None, seconds=55):
    """Do not advertise a tunnel unless our own FastAPI responded successfully."""
    import urllib.request
    import json
    from app.version import VERSION
    expected_version = VERSION if expected_version is None else expected_version
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if bot_process.poll() is not None:
            raise StartupError('Сервер или Telegram-бот завершился при запуске. Посмотрите сообщение выше.')
        try:
            with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1.5) as response:
                result = json.load(response)
            if result.get('ok') is True and result.get('version') == expected_version:
                return
            raise StartupError('На порту 8000 отвечает другой сервер или неверная версия приложения.')
        except (OSError, ValueError, TimeoutError):
            time.sleep(0.5)
    raise StartupError('FastAPI не открыл /health за отведённое время. Проверьте сеть и токен.')


def reset_temporary_menu(bot_token):
    """Remove the expired Quick Tunnel menu button when the test run closes.

    This never deletes a webhook or modifies any messages or user data.
    """
    import httpx
    try:
        with httpx.Client(timeout=4.0, follow_redirects=False) as client:
            from app.telegram_transport import method_url, relay_headers
            response = client.post(method_url(bot_token, 'setChatMenuButton'),
                                   json={'menu_button': {'type': 'commands'}}, headers=relay_headers())
            response.raise_for_status()
            if response.json().get('ok') is not True:
                raise RuntimeError('Telegram did not confirm reset')
        print('[Tunnel] Временная кнопка Mini App удалена из меню бота.', flush=True)
        return True
    except Exception:
        print('[Tunnel] Не удалось сбросить меню бота. При следующем запуске /start даст свежую кнопку.', flush=True)
        return False


def main():
    if settings.demo_mode:
        raise SystemExit('[Tunnel] DEMO_MODE должен быть false. Запуск демо через Интернет запрещён.')
    if not settings.bot_token:
        raise SystemExit('[Tunnel] Сначала заполните BOT_TOKEN в .env через @BotFather.')
    # Critical: Cloudflare must never route users to an unrelated process on 8000.
    assert_port_free()
    exe=locate_cloudflared()
    if not exe:
        raise SystemExit('[Tunnel] Не найден cloudflared. Скачайте его с https://developers.cloudflare.com/tunnel/downloads/ и положите в .tools\\cloudflared.exe')
    print('[Tunnel] Запуск временной HTTPS-ссылки для Telegram Mini App...',flush=True)
    tunnel,url=start_tunnel(exe)
    print('[Tunnel] HTTPS-адрес получен; проверяем запуск собственного сервера.',flush=True)
    env=os.environ.copy()
    env['WEBAPP_URL']=url
    env['DEMO_MODE']='false'
    bot=None
    interrupted=False
    tunnel_lost=False
    try:
        bot=subprocess.Popen([sys.executable,'-m','app.main'],env=env,cwd=str(ROOT))
        wait_for_our_api(bot)
        if tunnel.poll() is not None:
            raise StartupError('HTTPS-туннель уже завершился: ссылка Mini App недоступна.')
        print(f'[Tunnel] Mini App: {url}',flush=True)
        print('[Tunnel] Отправьте /start или /app в Telegram и откройте новую кнопку.',flush=True)
        while bot.poll() is None:
            if tunnel.poll() is not None:
                print('[Tunnel] Соединение закрыто; прекращаем запуск, чтобы не использовать устаревшую Mini App-ссылку.',flush=True)
                tunnel_lost=True
                break
            time.sleep(1)
    except KeyboardInterrupt:
        interrupted=True
        print('\n[Tunnel] Останавливаем бот и Mini App.',flush=True)
    finally:
        for child in (bot,tunnel):
            if child and child.poll() is None:
                child.terminate()
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill()
        reset_temporary_menu(settings.bot_token)
    if not interrupted and not tunnel_lost and bot and bot.returncode not in (0,None):
        raise SystemExit(bot.returncode)
    if tunnel_lost:
        raise SystemExit(2)


if __name__=='__main__':
    try:
        main()
    except (StartupError, RuntimeError) as error:
        print('[Tunnel ERROR]', error, flush=True)
        raise SystemExit(1) from None

