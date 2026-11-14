"""Sessions (same hours as web/src/lib/sessions.ts) and the intraday time rules."""
from datetime import datetime, time, timezone

from data.symbols import parse_symbol
from intraday.config import IntradayConfig, parse_symbol_map
from intraday.sessions import (active_sessions, entries_allowed, flat_time, next_forex_open, session_key,
                               session_label)

EU = parse_symbol("EUR/USD")
UJ = parse_symbol("USD/JPY")
CFG = IntradayConfig()


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_sessions_follow_local_time_and_dst():
    # Wed 11 Nov 2026 (winter time): London 08-17 UTC, New York 13-22 UTC, Tokyo 00-09 UTC
    assert active_sessions(utc(2026, 11, 11, 3)) == ["Asian"]
    assert session_label(utc(2026, 11, 11, 10)) == "London session"
    assert session_label(utc(2026, 11, 11, 14)) == "London–New York overlap"
    assert session_key(utc(2026, 11, 11, 14)) == "overlap"
    # summer (Wed 15 Jul 2026): New York opens 12:00 UTC
    assert "New York" in active_sessions(utc(2026, 7, 15, 12, 30))
    assert "New York" not in active_sessions(utc(2026, 11, 11, 12, 30))
    assert session_label(utc(2026, 11, 14, 10)) == "Market closed (weekend)"


def test_next_open_is_sunday_17_new_york():
    assert next_forex_open(utc(2026, 11, 14, 10)) == utc(2026, 11, 15, 22)   # Sun 17:00 EST = 22:00 UTC


def test_entry_rules_cutoff_quiet_session_and_weekend():
    ok, code, _ = entries_allowed(utc(2026, 11, 11, 10), EU, CFG)
    assert ok and code is None
    ok, code, txt = entries_allowed(utc(2026, 11, 11, 17, 5), EU, CFG)       # 18:05 Berlin
    assert not ok and code == "after_cutoff" and "18:00" in txt
    ok, code, _ = entries_allowed(utc(2026, 11, 11, 3), EU, CFG)              # Asian only: quiet for EUR/USD
    assert not ok and code == "quiet_session"
    assert entries_allowed(utc(2026, 11, 11, 3), UJ, CFG)[0]                  # but fine for USD/JPY
    ok, code, txt = entries_allowed(utc(2026, 11, 14, 10), EU, CFG)
    assert not ok and code == "market_closed" and "Sun 23:00" in txt


def test_flat_time_and_config_parsing():
    assert flat_time(utc(2026, 11, 11, 10), CFG) == utc(2026, 11, 11, 20, 30)     # 21:30 Berlin (CET)
    assert flat_time(utc(2026, 7, 15, 10), CFG) == utc(2026, 7, 15, 19, 30)       # 21:30 CEST
    cfg = IntradayConfig(no_new_entries_after=time(16, 0))
    assert entries_allowed(utc(2026, 11, 11, 15, 30), EU, cfg)[1] == "after_cutoff"
    assert parse_symbol_map("EUR/USD:2.0, xau/usd:50,default:3") == {"EUR/USD": 2.0, "XAU/USD": 50.0, "default": 3.0}
