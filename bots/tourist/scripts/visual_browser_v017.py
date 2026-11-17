"""Visual Chromium QA (signed Telegram fixtures, actual styles and image files embedded).
No external network, client credentials or production database.
"""
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
import re,base64,json,shutil,sys
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app import api,config,database,service,sheets,notifications,maintenance,assistant
from scripts.telegram_flow_smoke import SYNTHETIC_TOKEN,sign_init_data
from scripts.telegram_mode_browser_smoke import page_content
ROOT=Path(__file__).resolve().parents[1]
VISUAL=ROOT/'web/visual/v017'

def visual_html(signed):
    doc=page_content(signed)
    css=(ROOT/'web/tourist-v017.css').read_text(encoding='utf-8')
    polish=(ROOT/'web/tourist-v018.css').read_text(encoding='utf-8')
    font=(ROOT/'web/fonts/stengazeta.ttf')
    if font.exists():
        polish=polish.replace('/assets/fonts/stengazeta.ttf','data:font/ttf;base64,'+base64.b64encode(font.read_bytes()).decode('ascii'))
    doc=re.sub(r'<link rel="stylesheet" href="/assets/tourist-v017.css\?v=.*?">','<style>'+css+'</style>',doc)
    doc=re.sub(r'<link rel="stylesheet" href="/assets/tourist-v018.css\?v=.*?">','<style>'+polish+'</style>',doc)
    # Preserve actual inline SVG and PNG pixels in the browser despite local network restrictions.
    asset_map={}
    for file in VISUAL.rglob('*'):
        if not file.is_file() or file.suffix not in ('.png','.svg'):continue
        path=file.relative_to(VISUAL).as_posix()
        mime='image/svg+xml' if file.suffix=='.svg' else 'image/png'
        asset_map[path]='data:'+mime+';base64,'+base64.b64encode(file.read_bytes()).decode('ascii')
    for key,value in asset_map.items():
        doc=doc.replace('/assets/visual/v017/'+key,value)
    doc=doc.replace('</head>', '<script>window.__v17QAAssets='+json.dumps(asset_map,separators=(',',':'))+';</script></head>')
    return doc

def main():
    with TemporaryDirectory(prefix='tourist_v017_visual_') as tmp:
        cfg=replace(config.settings,database_path=str(Path(tmp)/'visual.sqlite3'),bot_token=SYNTHETIC_TOKEN,
                    demo_mode=False,showcase_mode=True,owner_telegram_id=710001,google_sheet_id='',google_credentials_file='',backup_interval_hours=0)
        for module in (config,database,service,api,sheets,notifications,maintenance,assistant):module.settings=cfg
        database.initialize_storage()
        (ROOT/'qa').mkdir(exist_ok=True)
        with TestClient(api.app) as client,sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=shutil.which('chromium') or shutil.which('google-chrome'),args=['--no-sandbox'] if sys.platform!='win32' else [])
            for width in (390,):
                pg=browser.new_page(viewport={'width':width,'height':844},device_scale_factor=1)
                errors=[]
                pg.on('pageerror',lambda e:errors.append(str(e)))
                def bridge(url,options):
                    response=client.request(options.get('method','GET'),url,headers=options.get('headers',{}),content=options.get('body'))
                    return {'status':response.status_code,'body':response.text}
                pg.expose_function('bridgeFetch',bridge)
                pg.set_content(visual_html(sign_init_data(SYNTHETIC_TOKEN,710002,'Гость')),wait_until='load',timeout=120000)
                pg.wait_for_function("document.querySelector('#booking-days .day-chip') !== null",timeout=18000)
                assert pg.locator('.game-card img').count()==4
                pg.locator('.game-card.karaoke').click()
                assert 'караоке' in pg.locator('#support-message').input_value().lower()
                pg.locator('.bottom-nav button[data-screen="home"]').click()
                pg.locator('.game-card.mafia').click()
                assert pg.locator('#event-list .event-item').count()>=2
                pg.locator('.bottom-nav button[data-screen="home"]').click()
                assert pg.evaluate("getComputedStyle(document.querySelector('.hero')).backgroundImage.includes('data:image/png;base64')")
                assert pg.evaluate("[...document.querySelectorAll('.game-card img, .nav-symbol img')].every(el=>el.complete&&el.naturalWidth>0)")
                assert not pg.evaluate('document.documentElement.scrollWidth > innerWidth'),'home overflow'
                if width==390:pg.screenshot(path=str(ROOT/'qa/v017_home.png'),full_page=True)
                pg.locator('.bottom-nav button[data-screen="schedule"]').click()
                pg.locator('.chip[data-kind="all"]').click()
                assert pg.locator('#event-list .event-item').count()>=3
                assert not pg.evaluate('document.documentElement.scrollWidth > innerWidth'),'events overflow'
                if width==390:pg.screenshot(path=str(ROOT/'qa/v017_events.png'),full_page=True)
                pg.locator('.bottom-nav button[data-screen="billiard"]').click()
                assert pg.locator('#booking-days .day-chip').count()==7
                assert pg.locator('#booking-times .time-chip').count()==8
                pg.locator('[data-duration="3"]').click()
                assert pg.locator('#bill-hours').input_value()=='3'
                assert '700' in pg.locator('#booking-summary-total').inner_text()
                pg.locator('[data-bill-time="20:00"]').click()
                assert pg.locator('#bill-start').input_value().endswith('T20:00')
                pg.locator('[data-show-booking-info]').click()
                assert pg.locator('#result-popup').is_visible()
                pg.locator('[data-popup-close]').last.click()
                assert not pg.locator('#result-popup').is_visible()
                assert not pg.evaluate('document.documentElement.scrollWidth > innerWidth'),'booking overflow'
                if width==390:pg.screenshot(path=str(ROOT/'qa/v017_billiard.png'),full_page=True)
                pg.locator('.bottom-nav button[data-screen="chat"]').click()
                pg.locator('#chat-question').fill('Добрый вечер, где вы находитесь?')
                pg.locator('#chat-form button[type="submit"]').click()
                pg.locator('#chat-messages').get_by_text('Кукунина',exact=False).wait_for(timeout=12000)
                pg.locator('.bottom-nav button[data-screen="support"]').click()
                assert not pg.evaluate('document.documentElement.scrollWidth > innerWidth'),'support overflow'
                if width==390:pg.screenshot(path=str(ROOT/'qa/v017_support.png'),full_page=True)
                assert not errors,errors
                for smaller in (320,360,430,768):
                    pg.set_viewport_size({'width':smaller,'height':844})
                    for screen in ('home','schedule','billiard','chat','support','profile'):
                        pg.locator(f'.bottom-nav button[data-screen="{screen}"]').click()
                        assert not pg.evaluate('document.documentElement.scrollWidth > innerWidth'),f'{screen} overflow at {smaller}'
                pg.close()
                print('PASS:',width,'px, assets, navigation, events, booking, live total, popup, chat and support')
            browser.close()
if __name__=='__main__':main()
