"""Telegram alerts via a personal bot (free).

Setup: talk to @BotFather in Telegram -> /newbot -> copy the token into TELEGRAM_BOT_TOKEN. Then send any message
to your new bot and run `python -m alerts.telegram --chat-id` to print your chat id for TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import argparse
import logging

import requests

from config.settings import get_settings

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000  # Telegram's limit is 4096 characters


class TelegramNotifier:
    name = "telegram"

    def __init__(self, token: str | None = None, chat_id: str | None = None, session=None):
        s = get_settings()
        self.token = token if token is not None else s.telegram_bot_token
        self.chat_id = chat_id if chat_id is not None else s.telegram_chat_id
        self.http = session or requests

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> bool:
        if not self.configured:
            log.info("Telegram not configured; alert not sent")
            return False
        ok = True
        for i in range(0, len(text), MAX_LEN):
            try:
                r = self.http.post(API.format(token=self.token, method="sendMessage"),
                                   json={"chat_id": self.chat_id, "text": text[i:i + MAX_LEN],
                                         "disable_web_page_preview": True}, timeout=15)
                if r.status_code != 200:
                    log.warning("Telegram HTTP %s: %s", r.status_code, r.text[:200])
                    ok = False
            except requests.RequestException as e:
                log.warning("Telegram send failed: %s", e)
                ok = False
        return ok

    def find_chat_ids(self) -> list[dict]:
        """Chats that recently messaged the bot (to discover TELEGRAM_CHAT_ID)."""
        r = self.http.get(API.format(token=self.token, method="getUpdates"), timeout=15)
        r.raise_for_status()
        out = {}
        for u in r.json().get("result", []):
            chat = (u.get("message") or u.get("channel_post") or {}).get("chat") or {}
            if chat.get("id") is not None:
                out[chat["id"]] = {"chat_id": chat["id"], "name": chat.get("username") or chat.get("title") or chat.get("first_name")}
        return list(out.values())


def main() -> None:
    p = argparse.ArgumentParser(description="Telegram alert helper")
    p.add_argument("--chat-id", action="store_true", help="print the chat ids that messaged your bot")
    p.add_argument("--test", action="store_true", help="send a test message")
    a = p.parse_args()
    t = TelegramNotifier()
    if not t.token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first (from @BotFather).")
    if a.chat_id:
        ids = t.find_chat_ids()
        print("\n".join(f"{c['chat_id']}  ({c['name']})" for c in ids) or "No chats yet: send any message to your bot first.")
    if a.test:
        print("sent" if t.send("✅ ShreeAgent AI: Telegram alerts are working.") else "NOT sent (check token and chat id)")


if __name__ == "__main__":
    main()
