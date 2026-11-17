from __future__ import annotations

from collections.abc import Awaitable, Callable

from .config import Settings
from .db import Database
from .responder import BotAnswer

TelegramSender = Callable[[int, str], Awaitable[None]]
TelegramManagerSender = Callable[[str, int | None], Awaitable[int]]
TelegramConversationMarker = Callable[[int, bool], Awaitable[None]]


class OperatorBridge:
    """Telegram-only human handoff. The manager works in the private chat."""

    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._telegram_sender: TelegramSender | None = None
        self._telegram_manager_sender: TelegramManagerSender | None = None
        self._telegram_marker: TelegramConversationMarker | None = None

    def set_telegram_sender(self, sender: TelegramSender) -> None:
        self._telegram_sender = sender

    def set_telegram_manager_sender(self, sender: TelegramManagerSender) -> None:
        self._telegram_manager_sender = sender

    def set_telegram_marker(self, marker: TelegramConversationMarker) -> None:
        self._telegram_marker = marker

    def available(self) -> bool:
        return self._telegram_manager_sender is not None

    async def escalate(self, *, platform: str, user_id: int, chat_id: int, username: str | None,
                       full_name: str, question: str, answer: BotAnswer) -> int | None:
        if platform != "telegram" or not self.available():
            return None

        ticket_id = self.db.create_ticket(
            platform="telegram", user_id=user_id, chat_id=chat_id, username=username, full_name=full_name,
            question=question, reason=answer.reason, confidence=answer.confidence,
        )
        profile = f"https://t.me/{username}" if username else f"Telegram ID: {user_id}"
        live_note = ""
        if answer.reason == "dynamic_availability":
            live_note = "⚡ Нужно проверить актуальную доступность / бронирование.\n\n"
        card = (
            f"🆘 Новый вопрос #{ticket_id}\n\n"
            f"👤 {full_name or f'Telegram ID {user_id}'}\n"
            f"🔹 Профиль: {profile}\n\n"
            f"{live_note}"
            f"💬 Вопрос:\n{question}\n\n"
            "Нажмите «✍ Ответить» или отправьте:\n"
            f"#{ticket_id} Ваш ответ"
        )
        try:
            message_id = await self._telegram_manager_sender(card, ticket_id)
            if message_id:
                self.db.set_support_message(ticket_id, message_id)
            if self._telegram_marker:
                try:
                    await self._telegram_marker(chat_id, True)
                except Exception as exc:
                    print(f"[support] cannot mark Telegram chat: {exc}", flush=True)
            return ticket_id
        except Exception as exc:
            print(f"[support] Telegram manager cannot receive ticket #{ticket_id}: {type(exc).__name__}: {exc}", flush=True)
            self.db.mark_failed(ticket_id)
            return None

    async def escalate_intake(self, *, user_id: int, chat_id: int, username: str | None, full_name: str,
                              question: str, intake_type: str, intake_title: str, intake_payload: dict,
                              priority: str = "normal", summary_text: str = "") -> int | None:
        """Deliver a structured Smart Handoff ticket to the same Telegram manager inbox."""
        if not self.available():
            return None
        request_id = str((intake_payload or {}).get("request_id") or "").strip() or None
        existing = self.db.get_ticket_by_intake_request(request_id) if request_id else None
        if existing is not None:
            # A container may have restarted after creating/delivering the ticket but before the
            # parent intake session was cleared. Reuse the same ticket instead of duplicating it.
            ticket_id = int(existing["id"])
            if existing["support_message_id"]:
                return ticket_id
            if str(existing["status"] or "") == "failed":
                self.db.reopen_failed_ticket(ticket_id)
        else:
            ticket_id = self.db.create_ticket(
                platform="telegram", user_id=user_id, chat_id=chat_id, username=username, full_name=full_name,
                question=question, reason="smart_handoff", confidence=1.0, intake_type=intake_type,
                intake_payload=intake_payload, priority=priority, intake_request_id=request_id,
            )
        profile = f"https://t.me/{username}" if username else f"Telegram ID: {user_id}"
        icon = {"urgent": "🔴 СРОЧНО", "high": "🟠 ВЫСОКИЙ ПРИОРИТЕТ", "low": "🟢 НЕ СРОЧНО"}.get(priority, "🟡 ЗАЯВКА")
        card = (
            f"{icon} · Smart Handoff #{ticket_id}\n\n"
            f"📌 {intake_title}\n"
            f"👤 {full_name or f'Telegram ID {user_id}'}\n"
            f"🔹 Профиль: {profile}\n\n"
            f"{summary_text.strip()}\n\n"
            "Нажмите «✍ Ответить» или отправьте:\n"
            f"#{ticket_id} Ваш ответ"
        )
        try:
            message_id = await self._telegram_manager_sender(card, ticket_id)  # type: ignore[misc]
            if message_id:
                self.db.set_support_message(ticket_id, message_id)
            if self._telegram_marker:
                try:
                    await self._telegram_marker(chat_id, True)
                except Exception as exc:
                    print(f"[support] cannot mark Telegram chat: {exc}", flush=True)
            return ticket_id
        except Exception as exc:
            print(f"[support] Telegram manager cannot receive Smart Handoff #{ticket_id}: {type(exc).__name__}: {exc}", flush=True)
            self.db.mark_failed(ticket_id)
            return None

    async def deliver_human_answer(self, ticket, answer_text: str) -> tuple[bool, str | None]:
        if str(ticket["platform"] or "") != "telegram":
            return False, "v5.7 Telegram-only поддерживает возврат ответа только в Telegram"
        if self._telegram_sender is None:
            return False, "Telegram-адаптер сейчас не запущен"
        try:
            await self._telegram_sender(int(ticket["chat_id"]), "⭐ Ответ специалиста лагеря\n\n" + answer_text)
            self.db.save_human_answer(int(ticket["id"]), answer_text)
            if self._telegram_marker:
                try:
                    await self._telegram_marker(int(ticket["chat_id"]), False)
                except Exception as exc:
                    print(f"[support] cannot clear Telegram chat marks: {exc}", flush=True)
            return True, None
        except Exception as exc:
            return False, str(exc)
