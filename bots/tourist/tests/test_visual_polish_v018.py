"""Regression guarantees for the v0.18.0 locally-rendered polished Mini App."""
import hashlib,re
from pathlib import Path
from html.parser import HTMLParser
from app.version import VERSION
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'
HTML=(WEB/'index.html').read_text(encoding='utf-8')
CSS=(WEB/'tourist-v018.css').read_text(encoding='utf-8')
JS=(WEB/'app.js').read_text(encoding='utf-8')

class IdCollector(HTMLParser):
    def __init__(self):super().__init__();self.ids=[]
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if attrs.get('id'):self.ids.append(attrs['id'])

def test_18_release_version_cache_consistent():
    assert VERSION.startswith('0.18.3-')
    assert ROOT.joinpath('VERSION.txt').read_text().strip()==VERSION
    for name in ('styles.css','showcase.css','tourist-brand.css','tourist-v017.css','tourist-v018.css','app.js'):
        assert f'/assets/{name}?v={VERSION}' in HTML
    assert HTML.index('tourist-v017.css')<HTML.index('tourist-v018.css')<HTML.index('/assets/app.js')

def test_windows_bat_reports_correct_release_and_remains_one_click():
    text=ROOT.joinpath('START_TOURIST.bat').read_text()
    assert 'Version 0.18.3' in text
    assert 'scripts\\windows_one_click.ps1' in text
    assert ROOT.joinpath('scripts/windows_one_click.ps1').is_file()

def test_original_logo_is_identical_sha():
    assert hashlib.sha256(WEB.joinpath('tourist_logo_original.png').read_bytes()).hexdigest()=='dc07705cf3f9dd5f94de9b1479f875136addab4fe2d3dcbb847cdb8fa07f9930'

def test_modal_handles_keyboard_focus_and_scroll_lock():
    for phrase in ("popupPreviousFocus","dlg.querySelector('.popup-close').focus", "event.key==='Escape'","event.key!=='Tab'",'popup-open'):
        assert phrase in JS
    assert '.popup-open{overflow:hidden}' in CSS

def test_animation_is_local_and_reduced_motion_supported():
    for phrase in ('@keyframes touristViewEnter','@keyframes touristHeroEnter','@keyframes touristModalIn','@media(prefers-reduced-motion:reduce)', '.screen.active.entering'):
        assert phrase in CSS
    assert 'window.matchMedia' in JS
    assert 'https://cdn.jsdelivr.net/npm/vue' not in HTML
    assert 'https://unpkg.com/vue' not in HTML

def test_tappable_controls_have_real_html_and_selected_states():
    for key in ('data-screen="schedule"','data-screen="billiard"','data-bill-day','data-bill-time','data-duration','aria-pressed','result-popup'):
        assert key in JS or key in HTML
    assert 'booking-summary-total' in HTML and 'booking-summary-total' in JS
    assert 'select' in HTML

def test_nav_uses_6_unique_icons_and_accessible_labels():
    for label,icon in [('Главная','nav_home.svg'),('Афиша','nav_events.svg'),('Бильярд','nav_billiards.svg'),('Вопросы','nav_questions.svg'),('Связь','nav_contact.svg'),('Профиль','nav_profile.svg')]:
        assert icon in HTML and label in HTML
        assert WEB.joinpath('visual/v017/icons/nav',icon).exists()
    assert 'aria-current="page"' in HTML
    assert 'skip-link' in HTML

def test_every_document_id_is_unique():
    p=IdCollector();p.feed(HTML)
    assert len(p.ids)==len(set(p.ids)),[x for x in p.ids if p.ids.count(x)>1]

def test_animations_do_not_require_remote_fonts():
    assert 'googleapis.com' not in CSS
    assert '--stengazeta' in CSS and 'Arial Narrow' in CSS
    assert 'googleapis.com' not in CSS
    assert not (WEB/'fonts/stengazeta.ttf').exists()
    assert 'Bahnschrift' in CSS and 'Segoe UI' in CSS
    assert 'font-synthesis' in CSS

def test_all_static_hero_game_cards_present():
    for name in ('mafia','karaoke','poker','billiards'):
        assert WEB.joinpath(f'visual/v017/cards/{name}.png').is_file()
    assert WEB.joinpath('visual/v017/hero/lounge.png').is_file()

def test_owner_access_not_promoted_by_visual_code():
    assert "['owner','senior','admin'].includes(state.me?.user?.role)" in JS
    assert "if(state.me?.user?.role!=='owner')" in JS
    assert 'X-Telegram-Init-Data' in JS
