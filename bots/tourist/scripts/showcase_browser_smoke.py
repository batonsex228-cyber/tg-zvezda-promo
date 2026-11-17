"""Real Chromium two-account showcase UI test; all Telegram sessions synthetic."""
import shutil,sys,tempfile
from pathlib import Path
from dataclasses import replace
from fastapi.testclient import TestClient
from playwright.sync_api import sync_playwright
from app import config,database,api,service,sheets,notifications,maintenance,assistant
from scripts.telegram_mode_browser_smoke import page_content
from scripts.telegram_flow_smoke import SYNTHETIC_TOKEN, sign_init_data

ROOT=Path(__file__).resolve().parents[1]

def run():
    with tempfile.TemporaryDirectory(prefix='tourist_showcase_ui_') as tmp:
        cfg=replace(config.settings,database_path=str(Path(tmp)/'showcase.sqlite3'),
                    bot_token=SYNTHETIC_TOKEN,demo_mode=False,showcase_mode=True,
                    owner_telegram_id=710001,google_sheet_id='',google_credentials_file='',backup_interval_hours=0)
        for mod in (config,database,api,service,sheets,notifications,maintenance,assistant):mod.settings=cfg
        database.initialize_storage()
        assert len(service.list_events())==3
        with TestClient(api.app) as client,sync_playwright() as p:
            exe=shutil.which('chromium') or shutil.which('google-chrome')
            opts={'headless':True,'args':['--no-sandbox'] if sys.platform!='win32' else []}
            if exe:opts['executable_path']=exe
            browser=p.chromium.launch(**opts)
            errors=[]
            def new_page(tgid,name):
                pg=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=1)
                pg.on('pageerror',lambda e:errors.append(str(e)))
                pg.on('console',lambda e:errors.append(e.text) if e.type=='error' else None)
                def bridge(url,options):
                    res=client.request(options.get('method','GET'),url,headers=options.get('headers',{}),content=options.get('body'))
                    return {'status':res.status_code,'body':res.text}
                pg.expose_function('bridgeFetch',bridge)
                pg.set_content(page_content(sign_init_data(SYNTHETIC_TOKEN,tgid,name)),wait_until='load')
                pg.wait_for_function("document.querySelector('#booking-days .day-chip') !== null",timeout=12000)
                return pg
            guest=new_page(710002,'Гость')
            # Force a delayed profile response while the guest is typing. The
            # form must NEVER be reset by an in-flight background refresh.
            typed=guest.evaluate('''async () => {
              const original=window.fetch;
              window.fetch=(url,opts={}) => url==='/api/me'
                ? new Promise(resolve=>setTimeout(()=>resolve(original(url,opts)),200))
                : original(url,opts);
              try {
                const loading=loadMe();
                const input=document.querySelector('#full-name');
                input.value='Не стирать во время ввода';
                input.dispatchEvent(new Event('input',{bubbles:true}));
                await loading;
                return input.value;
              } finally { window.fetch=original; }
            }''')
            assert typed=='Не стирать во время ввода',f'Lost in-flight form input: {typed!r}'
            guest.locator('.bottom-nav button[data-screen="chat"]').click()
            guest.locator('#chat-question').fill('Добрый вечер, подскажите ваш адрес')
            guest.locator('#chat-form button[type="submit"]').click()
            guest.locator('#chat-messages').get_by_text('Кукунина',exact=False).wait_for(timeout=12000)
            guest.locator('#chat-question').fill('Сколько стоит мафия?')
            guest.locator('#chat-form button[type="submit"]').click()
            guest.locator('#chat-messages').get_by_text('600 ₽',exact=False).wait_for(timeout=12000)
            guest.screenshot(path=str(ROOT/'qa/tourist_chat.png'),full_page=True)
            guest.locator('.bottom-nav button[data-screen="home"]').click()
            assert guest.locator('#showcase-banner').count()==0, 'internal display banner leaked'
            assert guest.locator('#home-events .event-item').count()==2
            guest.locator('.bottom-nav button[data-screen="billiard"]').click()
            guest.locator('#booking-days .day-chip').nth(2).click()
            guest.locator('#booking-times button[data-bill-time="18:00"]').click()
            assert guest.locator('#bill-start').input_value().endswith('T18:00')
            guest.locator('button[data-screen="profile"]').first.click()
            guest.locator('#full-name').fill('Гость для брони')
            guest.locator('#phone').fill('+79991234567')
            guest.locator('#nickname').fill('Гость-Шоукейс')
            guest.locator('#profile-form button[type="submit"]').click()
            guest.get_by_text('Профиль сохранён.',exact=False).wait_for(timeout=10000)
            guest.locator('.bottom-nav button[data-screen="billiard"]').click()
            guest.locator('#billiard-form button[type="submit"]').click()
            guest.get_by_text('Заявка на бильярд отправлена',exact=False).wait_for(timeout=12000)
            guest.locator('.bottom-nav button[data-screen="billiard"]').click()
            guest.locator('#booking-times button[data-bill-time="18:00"]').wait_for(state='visible',timeout=10000)
            assert guest.locator('#booking-times button[data-bill-time="18:00"]').is_disabled()
            guest.locator('.bottom-nav button[data-screen="support"]').click()
            guest.locator('#support-message').fill('Можно привести друзей на мафию в субботу?')
            guest.locator('#support-form button[type="submit"]').click()
            guest.get_by_text('Вопрос №1 передан администратору',exact=False).wait_for(timeout=15000)
            assert guest.locator('#support-mine .support-item').count()==1
            owner=new_page(710001,'Владелец')
            owner.locator('#admin-nav').click()
            owner.locator('.admin-tab[data-admin-tab="support"]').click()
            owner.locator('#admin-support [data-support-reply="1"] textarea').wait_for(timeout=10000)
            owner.locator('#admin-support [data-support-reply="1"] textarea').fill('Конечно! Приходите с друзьями, но запись нужна каждому.')
            owner.locator('#admin-support [data-support-reply="1"] button[type="submit"]').click()
            owner.get_by_text('Ответ отправлен в очередь Telegram',exact=False).wait_for(timeout=15000)
            guest.locator('#refresh-support').click()
            guest.get_by_text('Конечно! Приходите с друзьями',exact=False).wait_for(timeout=15000)
            assert service.my_support_tickets(710002)[0]['status']=='answered'
            for pg in (guest,owner):
                if pg.evaluate('document.documentElement.scrollWidth > window.innerWidth'):
                    print('OVERFLOW', pg.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,items:[...document.querySelectorAll('*')].filter(e=>e.getBoundingClientRect().right>innerWidth+2).sort((a,b)=>b.getBoundingClientRect().right-a.getBoundingClientRect().right).slice(0,12).map(e=>[e.tagName,e.className,e.id,Math.round(e.getBoundingClientRect().left),Math.round(e.getBoundingClientRect().right)])})'''))
                assert not pg.evaluate('document.documentElement.scrollWidth > window.innerWidth'), 'horizontal overflow'
            assert not errors, errors
            (ROOT/'qa').mkdir(exist_ok=True)
            guest.locator('button[data-screen="home"]').first.click()
            guest.screenshot(path=str(ROOT/'qa/showcase_home.png'),full_page=True)
            guest.locator('.bottom-nav button[data-screen="support"]').click()
            guest.screenshot(path=str(ROOT/'qa/showcase_support.png'),full_page=True)
            owner.screenshot(path=str(ROOT/'qa/showcase_admin_support.png'),full_page=True)
            browser.close()
            print('PASS: showcase → guest question → staff reply → guest answer; mobile viewport, no JS errors')
if __name__=='__main__':run()
