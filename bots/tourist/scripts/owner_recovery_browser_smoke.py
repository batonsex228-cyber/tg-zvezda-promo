"""Offline Chromium check: owner reviews and manually retries transient delivery errors.

Uses a temporary SQLite database and a browser-to-TestClient bridge; no real
Telegram, Google or production database is accessed.
"""
import re
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright

from app import api, config, database, service, sheets, notifications, operations, maintenance

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='tourist_owner_recovery_') as folder:
        cfg = replace(config.settings, database_path=str(Path(folder)/'owner.sqlite3'),
                      bot_token='', demo_mode=True, owner_telegram_id=900001,
                      google_sheet_id='', google_credentials_file='')
        for m in (config, api, database, service, sheets, notifications, operations, maintenance):
            m.settings = cfg
        database.initialize_storage()
        service.ensure_user(900001, 'Владелец')
        with database.session(write=True) as c:
            service.enqueue(c, 900001, 'Не доставлено: тестовый системный статус')
            c.execute("UPDATE notification_outbox SET state='failed',last_error='HTTP 503'")
        html = (ROOT/'web/index.html').read_text('utf-8')
        css = (ROOT/'web/styles.css').read_text('utf-8')
        js = (ROOT/'web/app.js').read_text('utf-8')
        html = html.replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>', '')
        html = re.sub(r'<link rel="stylesheet" href="/assets/styles.css\?v=.*?">', '<style>'+css+'</style>', html)
        mock_fetch = '''<script>window.fetch=async (url,options={})=>{
          const r=await window.bridgeFetch(url,options);
          return new Response(r.body,{status:r.status,headers:{'Content-Type':'application/json'}});
        };</script>'''
        html = re.sub(r'<link rel="stylesheet" href="/assets/showcase.css\?v=.*?">', '<style>'+(ROOT/'web/showcase.css').read_text('utf-8')+'</style>', html)
        html = re.sub(r'<script src="/assets/app.js\?v=.*?" defer></script>', mock_fetch, html)
        html = html.replace('</body>', '<script>'+js+'</script></body>')
        with TestClient(api.app) as client, sync_playwright() as playwright:
            executable = shutil.which('chromium') or shutil.which('google-chrome')
            args = {'headless':True}
            if executable:
                args['executable_path'] = executable
            if sys.platform != 'win32':
                args['args']=['--no-sandbox']
            browser = playwright.chromium.launch(**args)
            page = browser.new_page(viewport={'width':390,'height':844}, device_scale_factor=1)
            js_errors = []
            page.on('pageerror',lambda exc: js_errors.append(str(exc)))
            page.on('dialog',lambda dialog:dialog.accept())
            def bridge(url, options):
                result = client.request(options.get('method','GET'),url,
                                        headers=options.get('headers',{}),content=options.get('body'))
                return {'status':result.status_code,'body':result.text}
            page.expose_function('bridgeFetch',bridge)
            page.set_content(html,wait_until='load',timeout=30000)
            page.locator('button[data-screen="admin"]').click()
            page.locator('#retry-notifications').wait_for(state='visible',timeout=12000)
            page.locator('#retry-notifications').click()
            page.get_by_text('Поставлено в очередь повторно: 1.').wait_for(timeout=12000)
            with database.session() as db:
                row = db.execute('SELECT state,attempts,last_error FROM notification_outbox').fetchone()
                assert row['state'] == 'pending' and row['attempts'] == 0 and row['last_error'] is None
            overflow = page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
            assert not js_errors, js_errors
            assert not overflow
            image = ROOT/'qa'/'browser_owner_recovery.png'
            page.screenshot(path=str(image),full_page=True)
            browser.close()
        print('PASS: owner Mini App recovery button, confirmation, API, SQLite, no JS errors or overflow')


if __name__=='__main__':
    main()
