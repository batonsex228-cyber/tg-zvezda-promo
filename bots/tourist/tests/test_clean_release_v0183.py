"""Client-facing presentation regressions for the clean v0.18.3 build."""
from pathlib import Path
from html.parser import HTMLParser
from app.version import VERSION
import hashlib

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
HTML = (WEB / 'index.html').read_text(encoding='utf-8')
JS = (WEB / 'app.js').read_text(encoding='utf-8')
CSS = (WEB / 'tourist-v018.css').read_text(encoding='utf-8')


def test_version_consistent_for_launcher_web_and_backend():
    assert VERSION == '0.18.3-clean-ui'
    assert (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() == VERSION
    assert b'Version 0.18.3' in (ROOT / 'START_TOURIST.bat').read_bytes()
    for asset in ('styles.css', 'showcase.css', 'tourist-brand.css', 'tourist-v017.css', 'tourist-v018.css', 'app.js'):
        assert f'/assets/{asset}?v={VERSION}' in HTML


def test_only_one_brand_logo_on_home_and_no_second_badge():
    # Logo in hidden chat tab is intentional, not an extra image over the hero.
    assert HTML.count('src="/assets/tourist_logo_original.png"') == 2
    assert 'class="hero-original-logo"' not in HTML
    assert '.hero-original-logo{' in (WEB / 'tourist-v017.css').read_text(encoding='utf-8')  # original CSS exists; no matching HTML
    assert hashlib.sha256((WEB / 'tourist_logo_original.png').read_bytes()).hexdigest() == 'dc07705cf3f9dd5f94de9b1479f875136addab4fe2d3dcbb847cdb8fa07f9930'


def test_no_superfluous_marketing_subtitles_pagination_or_header_buttons():
    for unwanted in ('hero-bottom', 'section-count', '01 / 03', 'НОВОМОСКОВСК · ВАШ ВЕЧЕР', 'ЖДЁМ В ГОСТИ · НОВОМОСКОВСК', 'header-actions', 'id="avatar"', 'id="connection-label"', 'brand-sub'):
        assert unwanted not in HTML
    assert 'class="brand-photo"' in HTML
    assert 'class="bottom-nav"' in HTML


def test_action_labels_do_not_include_arrows_or_arrow_icons():
    for value in ('↗', '➜', '→', 'icons/nav/ui_arrow.svg'):
        assert value not in HTML
        assert value not in JS
    assert "'Записаться'" in JS
    assert '<button type="submit" aria-label="Отправить вопрос">Отправить</button>' in HTML
    assert 'data-screen="schedule"' in HTML


def test_display_font_falls_back_without_bundling_font_assets():
    assert '--stengazeta' in CSS
    assert "'Arial Narrow'" in CSS
    assert '.hero h1 em' in CSS
    assert 'googleapis.com' not in CSS
    assert '--body-face' in CSS and '--display-face' in CSS


def test_image_delivery_keeps_visual_assets_light_and_transparent():
    paths = list((WEB / 'visual/v017').rglob('*.png'))
    assert len(paths) >= 40
    assert sum(p.stat().st_size for p in paths) < 2_800_000
    assert (WEB / 'visual/v017/cards/poker.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert (WEB / 'visual/v017/hero/lounge.png').is_file()


def test_live_inputs_and_booking_protection_are_untouched():
    for token in ('id="billiard-form"', 'id="booking-days"', 'id="booking-times"', 'id="booking-summary-total"', 'id="support-form"', 'id="profile-form"', 'data-screen="chat"', 'data-screen="profile"'):
        assert token in HTML
    for token in ("api('/api/assistant/reply'", "api('/api/admin/decide'", 'X-Telegram-Init-Data'):
        assert token in JS


def test_no_windows_unicode_filename_mojibake_in_working_tree():
    assert (ROOT / 'FAQ_150_ВОПРОСОВ_И_ОТВЕТОВ.md').is_file()
    assert (ROOT / 'НАЧНИТЕ_ЗДЕСЬ.md').is_file()
    assert not list(ROOT.glob('*╨*'))
