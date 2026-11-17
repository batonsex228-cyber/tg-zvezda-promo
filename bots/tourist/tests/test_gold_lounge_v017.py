"""Safeguards for production-grade interactive visual integration."""
from pathlib import Path
import re,hashlib
from app.version import VERSION
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'web'
VISUAL=WEB/'visual/v017'
ORIGINAL_SHA='dc07705cf3f9dd5f94de9b1479f875136addab4fe2d3dcbb847cdb8fa07f9930'

def test_release_is_v017():
    assert VERSION.startswith('0.18.3-')
    assert (ROOT/'VERSION.txt').read_text().strip()==VERSION

def test_authentic_logo_untouched():
    assert hashlib.sha256((WEB/'tourist_logo_original.png').read_bytes()).hexdigest()==ORIGINAL_SHA

def test_frontend_loads_live_css_last():
    html=(WEB/'index.html').read_text()
    assert f'/assets/tourist-v017.css?v={VERSION}' in html
    assert html.index('tourist-brand.css')<html.index('tourist-v017.css')<html.index('/assets/app.js')

def test_all_20_batch_icon_files_available():
    assert len(list((VISUAL/'icons/nav').glob('*.svg')))==10
    assert len(list((VISUAL/'icons/topics').glob('*.png')))==10

def test_all_10_empty_and_popup_assets_available():
    assert len(list((VISUAL/'illustrations').glob('*.png')))==10
    for path in (VISUAL/'illustrations').glob('*.png'):
        assert path.read_bytes().startswith(b'\x89PNG\r\n\x1a\n') and path.stat().st_size>1000

def test_every_bottom_tab_uses_real_button_with_vector_icon():
    html=(WEB/'index.html').read_text()
    for icon in ('nav_home','nav_events','nav_billiards','nav_questions','nav_contact','nav_profile'):
        assert f'icons/nav/{icon}.svg' in html
    for screen in ('home','schedule','billiard','chat','support','profile','admin'):
        assert f'data-screen="{screen}"' in html
    assert 'class="bottom-nav"' in html

def test_booking_controls_are_real_form_buttons():
    html=(WEB/'index.html').read_text()
    js=(WEB/'app.js').read_text()
    assert 'data-duration="1"' in html and 'data-duration="4"' in html
    assert 'data-duration' in js and 'data-bill-time' in js and 'data-bill-day' in js
    assert 'booking-summary-total' in js
    assert 'data-show-booking-info' in html and 'data-popup-close' in html

def test_sanitized_runtime_content_rendering_retained():
    js=(WEB/'app.js').read_text()
    assert 'escapeHtml' in js and 'state.pendingKeys' in js
    assert "api('/api/assistant/reply'" in js
    assert 'X-Telegram-Init-Data' in js
    assert 'button.dataset.prefill' in js and 'data-prefill=' in (WEB/'index.html').read_text()

def test_main_visuals_reference_actual_local_assets():
    css=(WEB/'tourist-v017.css').read_text()
    assert 'hero/lounge.png' in css
    assert 'billiard-banner' in css
    for name in ['mafia.png','karaoke.png','poker.png','billiards.png']:
        assert (VISUAL/'cards'/name).is_file()
    assert (VISUAL/'events/mafia.png').is_file()

def test_illustrations_do_not_replace_live_booking_data():
    html=(WEB/'index.html').read_text()
    for id in ('bill-start','bill-hours','bill-guests','booking-summary-total','booking-days','booking-times'):
        assert f'id="{id}"' in html
    assert 'id="result-popup"' in html
