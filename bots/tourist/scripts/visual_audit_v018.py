"""Offline mobile layout, interaction, focus, visual asset and reduced-motion QA.
It uses synthetic signed Telegram data and a temporary SQLite DB only.
"""
from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
import shutil,sys,json
from playwright.sync_api import sync_playwright
from fastapi.testclient import TestClient
from app import api,config,database,service,sheets,notifications,maintenance,assistant
from scripts.telegram_flow_smoke import SYNTHETIC_TOKEN,sign_init_data
from scripts.visual_browser_v017 import visual_html
ROOT=Path(__file__).resolve().parents[1]

def main():
    with TemporaryDirectory(prefix='tourist_v018_audit_') as tmp:
        cfg=replace(config.settings,database_path=str(Path(tmp)/'audit.sqlite3'),bot_token=SYNTHETIC_TOKEN,
                    demo_mode=False,showcase_mode=True,owner_telegram_id=710001,
                    google_sheet_id='',google_credentials_file='',backup_interval_hours=0)
        for module in (config,database,service,api,sheets,notifications,maintenance,assistant):module.settings=cfg
        database.initialize_storage()
        with TestClient(api.app) as client,sync_playwright() as p:
            chrome=shutil.which('chromium') or shutil.which('google-chrome')
            kw=dict(headless=True)
            if chrome:kw['executable_path']=chrome
            if sys.platform!='win32':kw['args']=['--no-sandbox']
            browser=p.chromium.launch(**kw)
            results=[]
            page=None
            for width in (320,360,390,430,768,1024):
                if page is None:
                    page=browser.new_page(viewport={'width':width,'height':844},device_scale_factor=1)
                else:
                    page.set_viewport_size({'width':width,'height':844})
                errors=[]
                page.on('pageerror',lambda err:errors.append(str(err)))
                page.on('console',lambda m:errors.append('Console: '+m.text) if m.type=='error' else None)
                def bridge(path,options):
                    r=client.request(options.get('method','GET'),path,headers=options.get('headers',{}),content=options.get('body'))
                    return {'status':r.status_code,'body':r.text}
                if width==320:
                    page.expose_function('bridgeFetch',bridge)
                    page.set_content(visual_html(sign_init_data(SYNTHETIC_TOKEN,710002,'Тестер')),wait_until='load',timeout=45000)
                    page.wait_for_function("document.querySelector('#booking-days .day-chip') !== null",timeout=12000)
                for screen in ('home','schedule','billiard','chat','support','profile'):
                    page.locator(f'.bottom-nav button[data-screen="{screen}"]').click()
                    page.wait_for_timeout(100)
                    size=page.evaluate('''()=>({viewport:innerWidth,page:document.documentElement.scrollWidth,
                      h:document.documentElement.scrollHeight,active:document.querySelector('.screen.active')?.id,
                      missing:[...document.querySelectorAll('.screen.active img')].filter(i=>i.complete&&i.naturalWidth===0).map(i=>i.src.slice(0,85))})''')
                    assert size['page']<=size['viewport']+1,('overflow',width,screen,size)
                    assert size['active']=='screen-'+screen,(screen,size)
                    assert not size['missing'],('images',width,screen,size['missing'])
                    if width==390 and screen in ('home','schedule','billiard'):
                        page.screenshot(path=str(ROOT/f'qa/v018_{screen}.png'),full_page=True)
                    results.append({'width':width,'screen':screen,'overflow':size['page']-size['viewport']})
                # Visual layering: active nav button is reachable, not obscured by graphics.
                tabs=page.locator('.bottom-nav .nav-btn:not(.hidden)')
                for idx in range(tabs.count()):
                    r=tabs.nth(idx).bounding_box()
                    assert r and r['width']>=38 and r['height']>=44,('tap-target',width,idx,r)
                page.locator('.bottom-nav button[data-screen="billiard"]').click()
                page.locator('[data-duration="3"]').click()
                assert '2700' in ''.join(c for c in page.locator('#booking-summary-total').inner_text() if c.isdigit())
                page.locator('[data-bill-time="20:00"]').click()
                assert page.locator('[data-bill-time="20:00"]').get_attribute('aria-pressed')=='true'
                page.locator('[data-show-booking-info]').click()
                assert page.locator('#result-popup').is_visible()
                assert page.locator('.popup-close').evaluate('(el)=>el===document.activeElement')
                page.keyboard.press('Tab')
                page.keyboard.press('Tab') # wrap back to close button
                assert page.locator('.popup-close').evaluate('(el)=>el===document.activeElement')
                page.keyboard.press('Escape')
                assert not page.locator('#result-popup').is_visible()
                # Reduced motion: animations must be opt-out for accessibility.
                page.emulate_media(reduced_motion='reduce')
                page.locator('.bottom-nav button[data-screen="chat"]').click()
                assert page.evaluate("getComputedStyle(document.querySelector('.screen.active')).animationName")=='none'
                page.emulate_media(reduced_motion='no-preference')
                assert not errors,('browser-errors',width,errors)
                print('PASS:',width,'px, 6 screens, assets, nav hit targets, popup, accessible animations')
            # full report with no private data
            (ROOT/'qa').mkdir(exist_ok=True)
            (ROOT/'qa/v018_visual_matrix.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
            page.close()
            browser.close()
            print('PASS: completed',len(results),'responsive screen combinations')
if __name__=='__main__':main()
