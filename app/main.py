from __future__ import annotations

import asyncio
import traceback
from pathlib import Path

from .booking import BookingEngine, AppsScriptBookingBackend
from .shift_booking import ShiftEngine
from .config import PROJECT_ROOT, Settings, load_settings
from .core import SupportCore
from .crawler import crawl_site
from .db import Database
from .knowledge import KnowledgeBase
from .intake import SmartHandoffEngine
from .operator import OperatorBridge
from .responder import StrictResponder
from .version import VERSION
from .telegram_adapter import TelegramAdapter

SEED_FILE = PROJECT_ROOT / "data" / "seed_faq.json"
BUNDLED_KB_FILE = PROJECT_ROOT / "data" / "knowledge_base.json"


async def run() -> int:
    print("\n============================================================")
    print(f" ZVEZDOCHKA SUPPORT BOT v{VERSION} — TELEGRAM-ONLY")
    print("============================================================")
    print("[1/4] Loading settings...")
    settings = load_settings()

    db = Database(settings.db_file)
    kb = KnowledgeBase(
        settings.kb_file,
        SEED_FILE,
        db,
        fallback_kb_file=BUNDLED_KB_FILE,
        max_age_hours=settings.kb_max_age_hours,
    )
    responder = StrictResponder(settings, kb)
    core = SupportCore(responder, show_source_links=settings.show_source_links)
    operator = OperatorBridge(settings, db)
    booking = None
    booking_disabled_reason: str | None = None
    if settings.bookings_enabled:
        if not settings.booking_api_url or not settings.booking_api_secret:
            booking_disabled_reason = "BOOKING_API_URL/BOOKING_API_SECRET are missing"
        elif not settings.telegram_manager_user_id:
            booking_disabled_reason = "TELEGRAM_MANAGER_USER_ID is required for manager approval"
        else:
            try:
                booking = BookingEngine(settings, db)
            except Exception as exc:
                booking_disabled_reason = f"{type(exc).__name__}: {exc}"
    intake = None
    intake_disabled_reason: str | None = None
    # The short "own event" request flow is always available when a manager inbox is configured.
    # The broader Smart Handoff scenarios still obey SMART_HANDOFF_ENABLED inside the engine.
    if settings.telegram_manager_user_id:
        try:
            intake = SmartHandoffEngine(settings, db)
        except Exception as exc:
            intake_disabled_reason = f"{type(exc).__name__}: {exc}"
    elif settings.smart_handoff_enabled:
        intake_disabled_reason = "TELEGRAM_MANAGER_USER_ID is required"

    shifts = None
    if settings.shift_bookings_enabled:
        from urllib.parse import urlparse
        policy = urlparse(settings.shift_privacy_policy_url)
        if (not settings.telegram_manager_user_id or policy.scheme != 'https' or not policy.netloc or not settings.shift_active_numbers):
            print('      Shift applications: OFF — configure manager, HTTPS privacy policy and active shifts', flush=True)
        else:
            shifts_backend = booking.backend if booking is not None else (AppsScriptBookingBackend(settings) if settings.booking_api_url and settings.booking_api_secret else None)
            shifts = ShiftEngine(settings, db, backend=shifts_backend)
            print('      Shift applications: ON (' + ('Google sync' if shifts_backend else 'local SQLite only') + ') — ' + ','.join(map(str,settings.shift_active_numbers)), flush=True)
    tg = TelegramAdapter(settings, core, db, operator, knowledge_base=kb, booking=booking, intake=intake, shifts=shifts)
    operator.set_telegram_sender(tg.send_plain_from_operator)
    operator.set_telegram_marker(tg.mark_support_conversation)
    if settings.telegram_manager_user_id:
        operator.set_telegram_manager_sender(tg.send_to_manager)

    print(f"      Telegram bot: {tg.bot_name or 'configured'}")
    print(f"      Telegram manager: {settings.telegram_manager_user_id or 'NOT CONFIGURED'}")
    print(f"      Website KB bundled pages: {len(kb.pages)}")
    print(f"      AI layer: {'ON (' + settings.openai_model + ')' if settings.openai_api_key else 'OFF (strict FAQ + human handoff)'}")
    if booking is not None:
        print("      Booking: ON (Google Sheet)")
    elif settings.bookings_enabled:
        print(f"      Booking: OFF — safe human handoff ({booking_disabled_reason or 'configuration error'})")
    else:
        print("      Booking: OFF (safe human handoff)")

    if settings.smart_handoff_enabled and intake is not None:
        print("      Smart Handoff: ON")
    elif settings.smart_handoff_enabled:
        print(f"      Smart Handoff: OFF — safe standard handoff ({intake_disabled_reason or 'configuration error'})")
    else:
        print("      Smart Handoff: OFF")
    print(f"      Event requests: {'ON' if intake is not None else 'OFF — manager inbox required'}")
    knowledge_loop_on = bool(settings.knowledge_loop_enabled and settings.telegram_manager_user_id)
    print(f"      Knowledge Loop: {'ON' if knowledge_loop_on else 'OFF'}")

    # Show only the trusted API origin, never a token-bearing URL or secret.
    print('      Telegram transport: ' +
          ('Cloudflare/HTTPS relay' if settings.telegram_api_base_url != 'https://api.telegram.org'
           else 'official direct API'))
    print("[2/4] Checking Telegram API...")
    await tg.validate()
    print(f"      Telegram API: OK" + (f" — @{tg.bot_name}" if tg.bot_name else ""))
    if settings.telegram_manager_user_id:
        try:
            allowed = await tg.manager_inbox_allowed()
            print(f"      Manager inbox: {'OK' if allowed else 'BLOCKED — manager must /start bot in private chat'}")
        except Exception as exc:
            print(f"      Manager inbox: could not verify ({exc})")
    if booking is not None:
        try:
            health = await booking.health()
            print(f"      Booking calendar: OK — API v{health.get('version') or '?'}")
        except Exception as exc:
            # Do not take the whole support bot down if Google is temporarily unavailable.
            # Booking requests themselves fail closed and are handed to a human.
            print(f"      Booking calendar: UNAVAILABLE — safe handoff mode ({type(exc).__name__}: {exc})")

    print("[3/4] Knowledge sources: site + local FAQ")

    async def refresh_loop() -> None:
        await asyncio.sleep(0.2)
        while True:
            try:
                payload = await crawl_site(settings.site_url, settings.kb_file, settings.crawl_max_pages)
                if payload.get("pages"):
                    kb.reload()
                    print(f"[kb] refreshed website: {len(payload['pages'])} pages; fresh={kb.is_fresh}", flush=True)
                else:
                    print("[kb] website refresh returned no pages; previous snapshot kept", flush=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"[kb] refresh failed: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(settings.kb_refresh_hours * 3600)

    print("[4/4] BOT STARTED")
    print("      Telegram long polling is running. Stop: Ctrl+C\n")
    refresh_task = asyncio.create_task(refresh_loop()) if settings.auto_refresh_kb else None
    try:
        await tg.run()
    finally:
        if refresh_task:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        await tg.close()
    return 0


def main() -> None:
    try:
        code = asyncio.run(run())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")
        code = 0
    except Exception as exc:
        print("\n============================================================")
        print(" BOT DID NOT START")
        print("============================================================")
        reason = str(exc)
        try:
            from dotenv import dotenv_values
            secret = dotenv_values(PROJECT_ROOT / ".env").get("TELEGRAM_BOT_TOKEN")
            if secret:
                reason = reason.replace(secret, "[TOKEN HIDDEN]")
        except Exception:
            pass
        print(f"Reason: {reason}")
        try:
            settings: Settings | None = load_settings()
        except Exception:
            settings = None
        if settings and settings.debug:
            traceback.print_exc()
        print("\nCheck Telegram bot token, or run START_TELEGRAM.bat again")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
