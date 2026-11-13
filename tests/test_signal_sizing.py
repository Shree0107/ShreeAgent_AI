"""Position size helper (signals/sizing.py) and market conventions (signals/market.py)."""
import pytest

from data.symbols import parse_symbol
from signals.market import conversion_rate, distance, fmt_distance, fmt_money, pip_size
from signals.sizing import position_size

EURUSD = parse_symbol("EUR/USD")


def eurusd(entry=1.1000, stop=1.0955, t1=1.1070, t2=1.1125, account=1000.0, risk=1.0, rate="auto"):
    if rate == "auto":
        rate = conversion_rate("USD", "EUR", EURUSD, entry)
    return position_size(EURUSD, entry, stop, t1, t2, account, risk, "EUR", rate, "USD")


def test_pip_sizes():
    assert pip_size(EURUSD) == 0.0001
    assert pip_size(parse_symbol("USD/JPY")) == 0.01
    assert pip_size(parse_symbol("XAU/USD")) == 0.1
    assert pip_size(parse_symbol("AAPL")) is None
    assert distance(EURUSD, 1.1000, 1.0955) == pytest.approx(45)
    assert fmt_distance(EURUSD, 1.1000, 1.0955) == "45 pips"
    assert fmt_distance(parse_symbol("AAPL"), 200, 190) == "5.0%"


def test_usd_to_eur_rate_comes_from_the_pair_itself():
    assert conversion_rate("USD", "EUR", EURUSD, 1.25) == pytest.approx(0.8)
    assert conversion_rate("EUR", "USD", EURUSD, 1.25) == pytest.approx(1.25)
    assert conversion_rate("EUR", "EUR") == 1.0


def test_eurusd_lots_for_eur_account():
    # €10,000 at 1% = €100 risk. 45-pip stop. 1 lot = 100,000 EUR: 1 pip = $10 = €9.0909 at 1.1000.
    p = eurusd(account=10_000, risk=1.0)
    per_lot_loss = 45 * 10 / 1.1000
    assert p.lots == pytest.approx(int(100 / per_lot_loss * 100) / 100)   # 0.24 lots, rounded DOWN
    assert p.lots == pytest.approx(0.24)
    assert p.units == pytest.approx(24_000)
    assert p.actual_risk <= p.risk_budget == 100
    assert p.currency == "EUR" and p.converted
    # margin at 1:30 on 24,000 EUR of notional
    assert p.margin_or_cost == pytest.approx(24_000 / 30, rel=1e-6)
    assert p.pip_value == pytest.approx(24_000 * 0.0001 / 1.1, abs=1e-4)
    assert p.gain_target1 == pytest.approx(24_000 * 0.0070 / 1.1, abs=0.01)


def test_rounding_never_exceeds_the_risk_budget():
    for account in (500, 1000, 2500, 7777, 20_000):
        for risk in (0.5, 1, 2):
            p = eurusd(account=account, risk=risk)
            assert p.actual_risk <= p.risk_budget + 1e-9


def test_too_small_account_is_flagged():
    # €200 at 1% = €2 risk; 0.01 lots on a 45-pip stop risks ~€4.09.
    p = eurusd(account=200, risk=1)
    assert p.too_small and p.lots == 0
    assert p.min_trade_risk == pytest.approx(0.01 * 100_000 * 0.0045 / 1.1, abs=0.01)


def test_stock_shares_with_currency_conversion():
    aapl = parse_symbol("AAPL")
    # €1,000 at 2% = €20. Stop $5 below entry, $1 = €0.90 -> €4.50 per share -> 4 shares.
    p = position_size(aapl, 200, 195, 210, 220, 1000, 2, "EUR", 0.9, "USD")
    assert p.units == 4 and p.lots is None
    assert p.actual_risk == pytest.approx(18.0)
    assert p.gain_target1 == pytest.approx(4 * 10 * 0.9)
    assert p.margin_or_cost == pytest.approx(4 * 200 * 0.9)


def test_missing_rate_falls_back_to_instrument_currency():
    p = eurusd(rate=None)
    assert not p.converted and p.currency == "USD"


def test_bad_inputs_raise():
    with pytest.raises(ValueError):
        eurusd(stop=1.1000)
    with pytest.raises(ValueError):
        eurusd(account=0)


def test_money_format():
    assert fmt_money(154.2, "EUR", signed=True) == "+€154"
    assert fmt_money(9.17, "EUR") == "€9.17"
    assert fmt_money(-2.5, "USD") == "−$2.50"
    assert fmt_money(12, "SEK") == "12.00 SEK"
