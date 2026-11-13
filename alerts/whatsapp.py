"""WhatsApp notifiers.

- CallMeBot: free and meant for personal alerts to your own number (one-time activation, see SETUP.md).
- Twilio: official WhatsApp Business API, more reliable, paid after the trial.
"""
from __future__ import annotations

import logging

import requests

from config.settings import get_settings

log = logging.getLogger(__name__)
MAX_LEN = 1500  # keep messages short; WhatsApp/Twilio cap is 1600 chars


class Notifier:
    name = "none"

    def send(self, text: str) -> bool:
        log.info("Alert (no WhatsApp backend configured):\n%s", text)
        return False


class CallMeBotNotifier(Notifier):
    name = "callmebot"
    URL = "https://api.callmebot.com/whatsapp.php"

    def __init__(self, phone: str, api_key: str):
        if not phone or not api_key:
            raise ValueError("CALLMEBOT_PHONE and CALLMEBOT_API_KEY must be set")
        self.phone, self.api_key = phone, api_key

    def send(self, text: str) -> bool:
        ok = True
        for chunk in split_message(text):
            r = requests.get(self.URL, params={"phone": self.phone, "text": chunk, "apikey": self.api_key}, timeout=30)
            if r.status_code != 200 or "error" in r.text.lower()[:200]:
                log.error("CallMeBot send failed: HTTP %s %s", r.status_code, r.text[:200])
                ok = False
        return ok


class TwilioNotifier(Notifier):
    name = "twilio"

    def __init__(self, sid: str, token: str, from_: str, to: str):
        if not all([sid, token, from_, to]):
            raise ValueError("TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM and TWILIO_WHATSAPP_TO must be set")
        self.sid, self.token = sid, token
        self.from_ = from_ if from_.startswith("whatsapp:") else f"whatsapp:{from_}"
        self.to = to if to.startswith("whatsapp:") else f"whatsapp:{to}"

    def send(self, text: str) -> bool:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        ok = True
        for chunk in split_message(text):
            r = requests.post(url, data={"From": self.from_, "To": self.to, "Body": chunk},
                              auth=(self.sid, self.token), timeout=30)
            if r.status_code >= 300:
                log.error("Twilio send failed: HTTP %s %s", r.status_code, r.text[:300])
                ok = False
        return ok


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split on line boundaries so each chunk fits one WhatsApp message."""
    chunks, cur = [], ""
    for line in text.splitlines():
        while len(line) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def get_notifier() -> Notifier:
    s = get_settings()
    if s.whatsapp_backend == "callmebot":
        return CallMeBotNotifier(s.callmebot_phone, s.callmebot_api_key)
    if s.whatsapp_backend == "twilio":
        return TwilioNotifier(s.twilio_account_sid, s.twilio_auth_token, s.twilio_whatsapp_from, s.twilio_whatsapp_to)
    return Notifier()
