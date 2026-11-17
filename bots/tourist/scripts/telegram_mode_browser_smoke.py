"""Offline Chromium rehearsal of REAL Telegram WebApp initData mode.

Tests the actual Mini App JS, signed API requests, separate guest/owner browsers,
admin decision and guest refresh. No connection to Telegram or production database.
Optional: requires Playwright + local Chromium.
"""
import json
import base64
import re
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app import api, config, database, notifications, service, sheets, maintenance, assistant
from scripts.telegram_flow_smoke import SYNTHETIC_TOKEN, sign_init_data

ROOT = Path(__file__).resolve().parents[1]


def page_content(signed):
    raw = (ROOT/'web/index.html').read_text(encoding='utf-8')
    css = (ROOT/'web/styles.css').read_text(encoding='utf-8')
    js = (ROOT/'web/app.js').read_text(encoding='utf-8')
    raw = re.sub(r'<script src="https://telegram.org/js/telegram-web-app.js"></script>', '', raw)
    raw = re.sub(r'<link rel="stylesheet" href="/assets/styles.css\?v=.*?">',
                 '<style>'+css+'</style>', raw)
    raw = re.sub(r'<link rel="stylesheet" href="/assets/showcase.css\?v=.*?">', '<style>'+(ROOT/'web/showcase.css').read_text(encoding='utf-8')+'</style>', raw)
    raw = re.sub(r'<link rel="stylesheet" href="/assets/tourist-brand.css\?v=.*?">', '<style>'+(ROOT/'web/tourist-brand.css').read_text(encoding='utf-8')+'</style>', raw)
    original_logo='data:image/png;base64,'+base64.b64encode((ROOT/'web/tourist_logo_original.png').read_bytes()).decode()
    raw=raw.replace('/assets/tourist_logo_original.png',original_logo)
    shim = ('<script>window.Telegram={WebApp:{initData:'+json.dumps(signed)+',ready(){},'
            'expand(){},HapticFeedback:{notificationOccurred(){}}}};'
            'window.fetch=async (url,options={})=>{const res=await window.bridgeFetch(url,options);'
            'return new Response(res.body,{status:res.status,headers:{"Content-Type":"application/json"}})};'
            '</script>')
    raw = re.sub(r'<script src="/assets/app.js\?v=.*?" defer></script>', shim, raw)
    return raw.replace('</body>', '<script>'+js+'</script></body>')


def run():
    with tempfile.TemporaryDirectory(prefix='tourist_browser_tg_') as tmp:
        cfg = replace(config.settings, database_path=str(Path(tmp)/'telegram_browser.sqlite3'),
                      demo_mode=False, bot_token=SYNTHETIC_TOKEN, owner_telegram_id=710001,
                      google_sheet_id='', google_credentials_file='', reminder_hours_before=0)
        for mod in (config,database,api,service,notifications,sheets,maintenance,assistant): mod.settings=cfg
        database.initialize_storage()
        service.ensure_user(710001,'Владелец')
        d=datetime.now(ZoneInfo(cfg.club_timezone))+timedelta(days=2)
        event = service.create_event(710001,'poker','Турнир для проверки Mini App',
                                     d.replace(hour=19,minute=0,second=0,microsecond=0).isoformat(),
                                     10,stack='5000',blinds='50/100')
        client=TestClient(api.app)  # No background notification task/no real network
        browser_errors=[]; console_errors=[]
        with sync_playwright() as p:
            executable=shutil.which('chromium') or shutil.which('google-chrome')
            launch={'headless':True}
            if executable:launch['executable_path']=executable
            if sys.platform!='win32':launch['args']=['--no-sandbox']
            browser=p.chromium.launch(**launch)
            def new_page(user_id,first_name):
                page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
                page.on('pageerror',lambda error:browser_errors.append(str(error)))
                page.on('console',lambda message:console_errors.append(message.text) if message.type=='error' else None)
                def bridge(url,opts):
                    r=client.request(opts.get('method','GET'),url,headers=opts.get('headers',{}),content=opts.get('body'))
                    return {'status':r.status_code,'body':r.text}
                page.expose_function('bridgeFetch',bridge)
                from scripts.visual_browser_v017 import visual_html
                page.set_content(visual_html(sign_init_data(SYNTHETIC_TOKEN,user_id,first_name)),wait_until='load')
                page.wait_for_function("document.querySelector('#booking-days .day-chip') !== null",timeout=15000)
                return page
            guest=new_page(710002,'Проверка')
            guest.locator('button[data-screen="profile"]').first.click()
            guest.locator('#full-name').fill('Тестовый игрок браузера')
            guest.locator('#phone').fill('+79990005544')
            guest.locator('#nickname').fill('Браузер-Тестер')
            guest.locator('#profile-form button[type="submit"]').click()
            guest.get_by_text('Профиль сохранён.',exact=False).wait_for(timeout=10000)
            guest.locator('.bottom-nav button[data-screen="schedule"]').click()
            guest.locator('#event-list button[data-join]').first.click()
            guest.get_by_text('Заявка отправлена.',exact=False).wait_for(timeout=10000)
            owner=new_page(710001,'Владелец')
            owner.locator('button[data-screen="admin"]').first.click()
            owner.locator('#backup-info').filter(has_text='ещё не создана').wait_for(timeout=10000)
            owner.locator('#operations-info').filter(has_text='База:').wait_for(timeout=10000)
            owner.locator('.admin-tab[data-admin-tab="pending"]').click()
            owner.locator('button[data-decide$=":1"]').first.wait_for(timeout=10000)
            owner.locator('button[data-decide$=":1"]').first.click()
            owner.get_by_text('Решение сохранено.',exact=False).wait_for(timeout=10000)
            guest.locator('button[data-screen="profile"]').first.click()
            guest.get_by_text('Подтверждено',exact=False).wait_for(timeout=10000)
            for page in (guest,owner):
                assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
            assert not browser_errors, browser_errors
            assert not console_errors, console_errors
            assert service.my_requests(710002)['events'][0]['status']=='confirmed'
            (ROOT/'qa').mkdir(exist_ok=True)
            guest.screenshot(path=str(ROOT/'qa'/'telegram_mode_guest.png'),full_page=True)
            owner.screenshot(path=str(ROOT/'qa'/'telegram_mode_admin.png'),full_page=True)
            browser.close()
            print(f'PASS: Telegram-mode Chromium (synthetic HMAC), event={event["id"]}, '
                  'guest registration, admin approval, user refresh, zero JS errors, no overflow')

if __name__=='__main__':run()
