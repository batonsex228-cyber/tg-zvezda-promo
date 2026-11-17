"""Extra mobile size QA for the branded Mini App; uses synthetic Telegram auth."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import shutil,sys
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app import config,database,api,service,sheets,notifications,maintenance,assistant
from scripts.telegram_flow_smoke import sign_init_data,SYNTHETIC_TOKEN
from scripts.telegram_mode_browser_smoke import page_content


def run():
    with TemporaryDirectory(prefix='tourist_viewports_') as tmp:
        cfg=replace(config.settings,database_path=str(Path(tmp)/'test.sqlite3'),showcase_mode=True,
                    bot_token=SYNTHETIC_TOKEN,owner_telegram_id=710001,demo_mode=False,
                    google_sheet_id='',google_credentials_file='',backup_interval_hours=0)
        for mod in (config,database,api,service,sheets,notifications,maintenance,assistant):mod.settings=cfg
        database.initialize_storage()
        with TestClient(api.app) as client, sync_playwright() as p:
            executable=shutil.which('chromium') or shutil.which('google-chrome')
            opts={'headless':True,'args':['--no-sandbox'] if sys.platform!='win32' else []}
            if executable:opts['executable_path']=executable
            browser=p.chromium.launch(**opts)
            for width in (320,360,375,390,430,768):
                page=browser.new_page(viewport={'width':width,'height':844},device_scale_factor=1)
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                def bridge(url, options):
                    res=client.request(options.get('method','GET'),url,headers=options.get('headers',{}),content=options.get('body'))
                    return {'status':res.status_code,'body':res.text}
                page.expose_function('bridgeFetch',bridge)
                page.set_content(page_content(sign_init_data(SYNTHETIC_TOKEN,710001,'Владелец')),wait_until='load')
                page.wait_for_function("document.querySelector('#booking-days .day-chip') !== null",timeout=15000)
                for tab in ('home','schedule','billiard','chat','support','profile','admin'):
                    page.evaluate('screen => go(screen)',tab)
                    page.wait_for_timeout(50)
                    actual=page.evaluate('document.documentElement.scrollWidth')
                    if actual>width:
                        print(f'OVERFLOW width={width} tab={tab}: scroll={actual}',flush=True)
                        print(page.evaluate("""() => [...document.querySelectorAll('*')]
                          .filter(e => e.getBoundingClientRect().right > innerWidth+1)
                          .slice(0,10).map(e => ({tag:e.tagName,klass:e.className,id:e.id,right:e.getBoundingClientRect().right}))"""),flush=True)
                        raise AssertionError('horizontal overflow')
                assert not errors,errors
                if width==390:
                    page.evaluate("go('home')")
                    page.screenshot(path=str(Path(__file__).resolve().parents[1]/'qa/v0161_home_phone.png'),full_page=True)
                    page.evaluate("go('chat')")
                    page.screenshot(path=str(Path(__file__).resolve().parents[1]/'qa/v0161_chat_phone.png'),full_page=True)
                page.close()
                print(f'PASS width={width}px, 7 screens',flush=True)
            browser.close()
if __name__=='__main__':run()
