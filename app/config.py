from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _path_env(name: str, default: str) -> Path:
    raw = os.getenv(name, default).strip()
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "да"}


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    """Optional feature knobs must not take the whole support bot down on a typo."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


def _bounded_float_env(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        return default
    return max(minimum, min(value, maximum))


def _normalize_site_url(raw: str) -> str:
    """Migrate the retired /new/ site prefix without requiring a server .env edit."""
    value = raw.strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if host == "zvezdaglazov.ru" and parsed.path.rstrip("/") == "/new":
        parsed = parsed._replace(path="/", query="", fragment="")
        value = urlunparse(parsed)
    return value


def _telegram_api_base_url(raw: str) -> str:
    """Return a Bot API origin. The token/method path is appended by the adapter.

    An explicit HTTPS relay is trusted to receive the BotFather token; reject
    paths, embedded credentials and URL fragments to prevent accidental routing.
    """
    value = (raw or 'https://api.telegram.org').strip().rstrip('/')
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError(
            'TELEGRAM_API_BASE_URL должен быть HTTPS-адресом без /bot, пути, логина и параметров.'
        )
    return value


@dataclass(frozen=True)
class Settings:
    site_url: str
    kb_file: Path
    db_file: Path
    crawl_max_pages: int
    openai_api_key: str | None
    openai_model: str
    faq_min_score: float
    retrieval_min_score: float
    camp_name: str
    debug: bool
    show_source_links: bool
    auto_refresh_kb: bool = True
    kb_refresh_hours: float = 6.0
    kb_max_age_hours: float = 24.0

    # Telegram-only polling runtime. Manager ID is optional for the FAQ bot.
    telegram_bot_token: str | None = None
    telegram_manager_user_id: int = 0
    # Optional HTTPS reverse proxy/Cloudflare Worker for Bot API requests.
    # Set only to a service you trust with the Telegram bot token and messages.
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_relay_key: str | None = None

    # Conversation quality / admin features.
    context_ttl_minutes: int = 15
    newsletters_enabled: bool = True

    # Optional booking module. Disabled until Google Apps Script is configured.
    bookings_enabled: bool = False
    booking_api_url: str | None = None
    booking_api_secret: str | None = None
    booking_timezone: str = "Europe/Samara"
    booking_hold_minutes: int = 15
    booking_timeout_seconds: float = 15.0

    # v6.0 Smart Handoff / reusable-knowledge loop. Opt-in for safe rollout.
    # Enable only after the new image is deployed and the manager flow is smoke-tested.
    smart_handoff_enabled: bool = False
    smart_handoff_ttl_minutes: int = 90
    knowledge_loop_enabled: bool = False
    # v6.0.4: disabled until updated Apps Script, privacy notice and manager are set.
    shift_bookings_enabled: bool = False
    shift_privacy_policy_url: str = ""
    shift_active_numbers: tuple[int, ...] = (1, 2, 3)
    shift_export_pii_to_google: bool = False


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    try:
        manager_id = int(os.getenv("TELEGRAM_MANAGER_USER_ID", "0") or 0)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_MANAGER_USER_ID должен быть числовым Telegram ID") from exc
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Нужен TELEGRAM_BOT_TOKEN. Запустите START_TELEGRAM.bat")

    faq_min_score = float(os.getenv("FAQ_MIN_SCORE", "0.72"))
    retrieval_min_score = float(os.getenv("RETRIEVAL_MIN_SCORE", "0.48"))
    if not 0 <= faq_min_score <= 1 or not 0 <= retrieval_min_score <= 1:
        raise RuntimeError("FAQ_MIN_SCORE и RETRIEVAL_MIN_SCORE должны быть от 0 до 1.")

    site_url = _normalize_site_url(os.getenv("SITE_URL", "https://zvezdaglazov.ru/"))
    parsed = urlparse(site_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("SITE_URL должен быть корректным http/https URL.")

    return Settings(
        site_url=site_url,
        kb_file=_path_env("KB_FILE", "runtime/knowledge_base.json"),
        db_file=_path_env("DB_FILE", "runtime/bot.sqlite3"),
        crawl_max_pages=max(1, min(int(os.getenv("CRAWL_MAX_PAGES", "40")), 200)),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip() or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna",
        faq_min_score=faq_min_score,
        retrieval_min_score=retrieval_min_score,
        camp_name=os.getenv("CAMP_NAME", "ДЗЛ «Звёздочка»").strip(),
        debug=_bool_env("DEBUG", False),
        show_source_links=_bool_env("SHOW_SOURCE_LINKS", True),
        auto_refresh_kb=_bool_env("AUTO_REFRESH_KB", True),
        kb_refresh_hours=max(1.0, float(os.getenv("KB_REFRESH_HOURS", "6"))),
        kb_max_age_hours=max(1.0, float(os.getenv("KB_MAX_AGE_HOURS", "24"))),
        telegram_bot_token=token,
        telegram_manager_user_id=manager_id,
        telegram_api_base_url=_telegram_api_base_url(
            os.getenv('TELEGRAM_API_BASE_URL', 'https://api.telegram.org')
        ),
        telegram_relay_key=os.getenv('TELEGRAM_RELAY_KEY', '').strip() or None,
        context_ttl_minutes=max(1, min(int(os.getenv("CONTEXT_TTL_MINUTES", "15")), 120)),
        newsletters_enabled=_bool_env("NEWSLETTERS_ENABLED", True),
        bookings_enabled=_bool_env("BOOKINGS_ENABLED", False),
        booking_api_url=os.getenv("BOOKING_API_URL", "").strip() or None,
        booking_api_secret=os.getenv("BOOKING_API_SECRET", "").strip() or None,
        booking_timezone=os.getenv("BOOKING_TIMEZONE", "Europe/Samara").strip() or "Europe/Samara",
        booking_hold_minutes=_bounded_int_env("BOOKING_HOLD_MINUTES", 15, 5, 60),
        booking_timeout_seconds=_bounded_float_env("BOOKING_TIMEOUT_SECONDS", 15.0, 3.0, 60.0),
        smart_handoff_enabled=_bool_env("SMART_HANDOFF_ENABLED", False),
        smart_handoff_ttl_minutes=_bounded_int_env("SMART_HANDOFF_TTL_MINUTES", 90, 15, 24 * 60),
        knowledge_loop_enabled=_bool_env("KNOWLEDGE_LOOP_ENABLED", False),
        shift_bookings_enabled=_bool_env("SHIFT_BOOKINGS_ENABLED", False),
        shift_privacy_policy_url=os.getenv("SHIFT_PRIVACY_POLICY_URL", "").strip(),
        shift_active_numbers=tuple(sorted({int(v) for v in os.getenv("SHIFT_ACTIVE_NUMBERS", "1,2,3").split(',') if v.strip() in {'1','2','3','4','5'}})),
        shift_export_pii_to_google=_bool_env("SHIFT_EXPORT_PII_TO_GOOGLE", False),
    )
