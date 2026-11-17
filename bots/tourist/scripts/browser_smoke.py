"""Optional real-Chromium Mini App smoke test.

Requires: pip install playwright && python -m playwright install chromium
Run: python -m scripts.browser_smoke
No real Telegram account or production database is touched.
"""
from pathlib import Path
import shutil
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
import sys, tempfile, re
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app import config, api, service, database, notifications, sheets

with tempfile.TemporaryDirectory() as tmp:
    cfg=replace(config.settings, database_path=str(Path(tmp)/'mini.sqlite3'),
                demo_mode=True, bot_token='',owner_telegram_id=900001,
                google_sheet_id='', google_credentials_file='')
    for mod in (config, api, service, database, sheets, notifications):
        mod.settings=cfg
    database.init_db();service.ensure_user(900001,'Владелец');service.ensure_user(100,'Новый гость')
    now=datetime.now(ZoneInfo(cfg.club_timezone))+timedelta(days=1)
    while now.weekday()!=3:now+=timedelta(days=1)
    start=now.replace(hour=19,minute=0,second=0,microsecond=0).isoformat()
    e=service.create_event(900001,'mafia','Тест браузера — мафия',start,10,'classic')
    raw=(ROOT/'web/index.html').read_text()
    css=(ROOT/'web/styles.css').read_text()
    js=(ROOT/'web/app.js').read_text()
    raw=re.sub(r'<script src="https://telegram.org/js/telegram-web-app.js"></script>', '', raw)
    raw=re.sub(r'<link rel="stylesheet" href="/assets/styles.css\?v=.*?">', '<style>'+css+'</style>',raw)
    raw=re.sub(r'<link rel="stylesheet" href="/assets/showcase.css\?v=.*?">', '<style>'+(ROOT/'web/showcase.css').read_text()+'</style>',raw)
    wire='''<script>
    window.fetch=async (url,options={})=>{
      const res=await window.bridgeFetch(url, options);
      return new Response(res.body,{status:res.status,headers:{'Content-Type':'application/json'}});
    };
    </script>'''
    raw=re.sub(r'<script src="/assets/app.js\?v=.*?" defer></script>',wire,raw)
    raw=raw.replace('</body>','<script>'+js+'</script></body>')
    with TestClient(api.app) as client,sync_playwright() as p:
        executable=shutil.which('chromium') or shutil.which('google-chrome')
        launch={'headless':True}
        if executable:launch['executable_path']=executable
        if sys.platform!='win32':launch['args']=['--no-sandbox']
        b=p.chromium.launch(**launch)
        page=b.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
        logs=[]; browser_errors=[]
        page.on('pageerror',lambda e:browser_errors.append(str(e)))
        page.on('console',lambda e: logs.append(f'{e.type}: {e.text}') if e.type=='error' else None)
        def bridge(url,opts):
            method=opts.get('method','GET')
            headers={k:v for k,v in opts.get('headers',{}).items()}
            payload=opts.get('body',None)
            res=client.request(method,url,headers=headers,content=payload)
            return {'status':res.status_code,'body':res.text}
        page.expose_function('bridgeFetch',bridge)
        page.set_content(raw,wait_until='load',timeout=20000)
        page.wait_for_function("document.querySelector('#booking-days .day-chip') !== null",timeout=10000)
        print('home OK:','ui-ready')
        page.locator('button[data-screen="profile"]').click()
        page.locator('#full-name').fill('Тестовый игрок')
        page.locator('#phone').fill('+79991234567')
        page.locator('#nickname').fill('Тестер')
        page.locator('#profile-form button[type="submit"]').click()
        page.get_by_text('Профиль сохранён.',exact=False).wait_for(timeout=10000)
        print('profile OK')
        page.locator('.bottom-nav button[data-screen="schedule"]').click()
        page.locator('#event-list button[data-join]').first.click()
        page.get_by_text('Заявка отправлена.',exact=False).wait_for(timeout=10000)
        print('join OK')
        page.locator('button[data-screen="admin"]').click()
        page.locator('.admin-tab[data-admin-tab="pending"]').click()
        page.locator('button[data-decide$=":1"]').first.wait_for(timeout=10000)
        page.locator('button[data-decide$=":1"]').first.click()
        page.get_by_text('Решение сохранено.',exact=False).wait_for(timeout=10000)
        print('admin approval OK')
        page.locator('button[data-screen="profile"]').click()
        page.get_by_text('Подтверждено').wait_for(timeout=10000)
        print('confirmed status OK')
        page.locator('.bottom-nav button[data-screen="billiard"]').click()
        future=datetime.now(ZoneInfo(cfg.club_timezone))+timedelta(days=2)
        page.locator('#bill-start').fill(future.replace(hour=16,minute=0,second=0,microsecond=0).strftime('%Y-%m-%dT%H:%M'))
        page.locator('#billiard-form button[type="submit"]').click()
        page.get_by_text('Заявка на бильярд отправлена',exact=False).wait_for(timeout=10000)
        print('billiard OK')
        page.locator('button[data-screen="admin"]').click()
        page.locator('button[data-admin-tab="overview"]').click()
        page.locator('#admin-metrics .metric').first.wait_for(timeout=10000)
        page.locator('#backup-info').filter(has_text='Локальное демо').wait_for(timeout=10000)
        page.locator('#operations-info').filter(has_text='База:').wait_for(timeout=10000)
        print('overview + backup status OK')
        # Administrator creates and edits a real event using the same Mini App controls.
        page.locator('.admin-tab[data-admin-tab="events"]').click()
        page.locator('#create-kind').select_option('poker')
        page.locator('#create-title').fill('Тестовый турнир')
        new_game=datetime.now(ZoneInfo(cfg.club_timezone))+timedelta(days=3)
        page.locator('#create-start').fill(new_game.replace(hour=19,minute=0,second=0,microsecond=0).strftime('%Y-%m-%dT%H:%M'))
        page.locator('#create-stack').fill('5000')
        page.locator('#create-blinds').fill('50/100')
        page.locator('#create-event-form button[type="submit"]').click()
        page.get_by_text('Мероприятие добавлено',exact=False).wait_for(timeout=10000)
        page.locator('#admin-events button[data-edit]').last.click()
        page.locator('#edit-title').fill('Тестовый турнир — обновлён')
        page.locator('#edit-status').select_option('closed')
        page.locator('#edit-event-form button[type="submit"]').click()
        page.get_by_text('Изменения мероприятия сохранены',exact=False).wait_for(timeout=10000)
        print('create and edit event OK')
        # Staff search and role assignment (the user must already have opened the bot).
        page.locator('.admin-tab[data-admin-tab="users"]').click()
        page.locator('#user-query').fill('100')
        page.locator('button[data-role-save="100"]').wait_for(timeout=10000)
        page.locator('select[data-role-for="100"]').select_option('admin')
        page.locator('button[data-role-save="100"]').click()
        page.get_by_text('Роль изменена',exact=False).wait_for(timeout=10000)
        page.locator('.admin-tab[data-admin-tab="audit"]').click()
        page.locator('#admin-audit .audit-row').first.wait_for(timeout=10000)
        print('user search, role and audit OK')
        (ROOT/'qa').mkdir(exist_ok=True)
        page.screenshot(path=str(ROOT/'qa'/'browser_admin.png'),full_page=True)
        page.locator('button[data-screen="home"]').first.click()
        page.screenshot(path=str(ROOT/'qa'/'browser_home.png'),full_page=True)
        print('browser errors:',browser_errors)
        print('console errors:',logs)
        print('viewport overflow:',page.evaluate('document.documentElement.scrollWidth > window.innerWidth'))
        assert not browser_errors and not logs
        assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        b.close()
