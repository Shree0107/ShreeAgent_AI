"""Position size helper: how much to buy so a stop-loss hit costs exactly the risk you chose (or less).

Forex : lots = risk money / (stop distance x units per lot, in account currency), rounded DOWN to the
        broker's lot step (XTB: 0.01 lots = 1,000 units of the base currency).
Stocks: shares = risk money / stop distance per share, rounded down to whole shares.
Rounding is always down, so the real risk never exceeds what you entered.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from data.symbols import Symbol
from signals.market import pip_size


@dataclass
class PositionSize:
    currency: str               # currency every money figure below is in
    risk_budget: float          # account x risk %
    units: float                # base-currency units (forex) or shares (stocks)
    lots: float | None          # forex only
    actual_risk: float          # loss if the stop is hit, at this size
    gain_target1: float
    gain_target2: float
    margin_or_cost: float       # forex: margin the broker holds; stocks: cost of the shares
    pip_value: float | None     # forex: money per pip at this size
    too_small: bool             # risk budget can't cover the smallest possible trade
    min_trade_risk: float       # what the smallest possible trade would risk
    converted: bool             # False if no FX rate was found and figures are in the instrument currency

    def as_dict(self) -> dict:
        return asdict(self)


def _floor_step(x: float, step: float) -> float:
    return round(math.floor(x / step + 1e-9) * step, 8)


def position_size(
    symbol: Symbol,
    entry: float,
    stop: float,
    target1: float,
    target2: float,
    account_size: float,
    risk_pct: float,
    account_currency: str,
    rate_to_account: float | None,
    instrument_currency: str,
    lot_size: int = 100_000,
    min_lot: float = 0.01,
    leverage: float = 30.0,
) -> PositionSize:
    """rate_to_account: account-currency value of 1 unit of the instrument currency (None = unknown)."""
    if account_size <= 0 or risk_pct <= 0:
        raise ValueError("Account size and risk % must be positive")
    per_unit = abs(entry - stop)
    if per_unit <= 0:
        raise ValueError("Entry and stop loss can't be the same price")
    converted = rate_to_account is not None
    conv = rate_to_account if converted else 1.0
    ccy = account_currency.upper() if converted else instrument_currency.upper()
    # Without a rate the budget is still in account currency; treat it 1:1 and say so (converted=False).
    budget = account_size * risk_pct / 100
    loss_per_unit = per_unit * conv

    if symbol.is_fx:
        lots = _floor_step(budget / loss_per_unit / lot_size, min_lot)
        too_small = lots < min_lot
        min_risk = min_lot * lot_size * loss_per_unit
        units = lots * lot_size
        pip = pip_size(symbol)
        pip_value = units * pip * conv
        margin = units * entry * conv / max(leverage, 1)
    else:
        units = float(math.floor(budget / loss_per_unit + 1e-9))
        lots, pip_value = None, None
        too_small = units < 1
        min_risk = loss_per_unit
        margin = units * entry * conv

    return PositionSize(
        currency=ccy, risk_budget=round(budget, 2), units=units, lots=lots,
        actual_risk=round(units * loss_per_unit, 2),
        gain_target1=round(units * abs(target1 - entry) * conv, 2),
        gain_target2=round(units * abs(target2 - entry) * conv, 2),
        margin_or_cost=round(margin, 2), pip_value=None if pip_value is None else round(pip_value, 4),
        too_small=too_small, min_trade_risk=round(min_risk, 2), converted=converted,
    )
