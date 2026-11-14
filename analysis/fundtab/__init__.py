"""Fundamentals tab (platform phase 8): calendar with plain-language meaning lines, central banks, currency
strength meter, news with optional AI one-liners, stock key numbers and the overall fundamental bias.

Every number shown comes from data or code. The LLM (optional) only rewords headlines, behind a number guard.
"""

# Short and long names used across the tab's plain-language sentences.
CURRENCY_NAME = {
    "USD": "the US dollar", "EUR": "the euro", "GBP": "the British pound", "JPY": "the Japanese yen",
    "CHF": "the Swiss franc", "AUD": "the Australian dollar", "CAD": "the Canadian dollar",
    "NZD": "the New Zealand dollar", "INR": "the Indian rupee", "CNY": "the Chinese yuan",
}
PLACE = {
    "USD": "the US", "EUR": "the euro area", "GBP": "the UK", "JPY": "Japan", "CHF": "Switzerland",
    "AUD": "Australia", "CAD": "Canada", "NZD": "New Zealand", "INR": "India", "CNY": "China",
}
ADJ = {
    "USD": "US", "EUR": "euro-area", "GBP": "UK", "JPY": "Japanese", "CHF": "Swiss", "AUD": "Australian",
    "CAD": "Canadian", "NZD": "New Zealand", "INR": "Indian", "CNY": "Chinese",
}
BANK_SHORT = {
    "USD": "Fed", "EUR": "ECB", "GBP": "BoE", "JPY": "BoJ", "CHF": "SNB", "AUD": "RBA", "CAD": "BoC",
    "NZD": "RBNZ", "INR": "RBI",
}
HOME_CURRENCY = {"US": "USD", "NSE": "INR", "BSE": "INR"}


def cur_name(c: str) -> str:
    return CURRENCY_NAME.get(c, c)


def symbol_currencies(symbol) -> list[str]:
    """Currencies whose news moves this symbol (gold/silver: the US dollar side)."""
    if symbol.is_fx:
        out = [c for c in (symbol.base, symbol.quote) if c not in ("XAU", "XAG")]
        return out or ["USD"]
    home = HOME_CURRENCY.get(symbol.market)
    return [home] if home else []
