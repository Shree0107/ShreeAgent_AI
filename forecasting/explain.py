"""Plain-language text for the Forecast tab. Every number comes from code; these are only templates."""
from __future__ import annotations

TF_LABEL = {"1m": "1-minute", "5m": "5-minute", "15m": "15-minute", "1h": "1-hour", "4h": "4-hour", "1d": "daily",
            "1wk": "weekly"}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400, "1wk": 604800}


def horizon_text(tf: str, horizon: int) -> str:
    """'4 hours', '24 hours', '5 trading days', '10 trading days'."""
    if tf == "1d":
        return f"{horizon} trading day{'s' if horizon != 1 else ''}"
    if tf == "1wk":
        return f"{horizon} week{'s' if horizon != 1 else ''}"
    secs = TF_SECONDS[tf] * horizon
    if secs < 3600:
        return f"{secs // 60} minutes"
    if secs <= 48 * 3600:
        hours = secs / 3600
        return f"{hours:g} hour{'s' if hours != 1 else ''}"
    days = round(secs / 86400)
    return f"{days} trading days"


def direction(last: float, median_end: float, q10_end: float, q90_end: float, prob_up: float) -> tuple[str, str]:
    """(code, words): the expected move measured against the width of the 80% range.

    code is 'up' | 'down' | 'flat'. A move smaller than a tenth of the half-width of the range, or a chance
    of rising between 45% and 55%, is 'flat': the model has no real opinion.
    """
    half = max((q90_end - q10_end) / 2, 1e-12)
    r = (median_end - last) / half
    if abs(r) < 0.1 or 0.45 < prob_up < 0.55:
        return "flat", "with no clear direction"
    word = "upward" if r > 0 else "downward"
    if abs(r) < 0.3:
        return ("up" if r > 0 else "down"), f"slightly {word}"
    if abs(r) < 0.6:
        return ("up" if r > 0 else "down"), word
    return ("up" if r > 0 else "down"), f"clearly {word}"


def summary_sentence(name: str, tf: str, horizon: int, last: float, median_end: float, q10_end: float,
                     q25_end: float, q75_end: float, q90_end: float, prob_up: float, fmt) -> str:
    """'The model expects EUR/USD to be between 1.0910 and 1.0960 in the next 4 hours, slightly upward. ...'"""
    _, words = direction(last, median_end, q10_end, q90_end, prob_up)
    ht = horizon_text(tf, horizon)
    s = (f"The model expects {name} to be between {fmt(q25_end)} and {fmt(q75_end)} in the next {ht}, {words}. "
         f"A wider range of {fmt(q10_end)} to {fmt(q90_end)} covers about 4 in 5 outcomes. ")
    pct = round(prob_up * 100)
    s += f"It gives about a {pct}% chance that the price ends higher than now ({fmt(last)})."
    return s


def verdict(bt: dict | None, name: str, tf: str) -> dict:
    """Plain verdict of the model vs simple baselines from the latest rolling backtest."""
    tfl = TF_LABEL.get(tf, tf)
    if not bt:
        return {"status": "unknown", "text": f"The model has not been checked on past {name} {tfl} data yet. "
                                              "Treat the forecast as a rough guide until it has."}
    if bt.get("n_windows", 0) < 10:
        return {"status": "unknown", "text": f"There is not enough {name} {tfl} history to check the model properly. "
                                              "Treat the forecast as a rough guide."}
    mae = bt["mae"]
    base = bt.get("baselines") or {"naive": {"mae": bt["naive_mae"]}}
    best_name, best = min(((k, v["mae"]) for k, v in base.items()), key=lambda kv: kv[1])
    from forecasting.baselines import LABELS

    best_label = LABELS.get(best_name, best_name).lower()
    naive_mae = bt["naive_mae"]
    gain = (1 - mae / naive_mae) * 100 if naive_mae > 0 else 0.0
    dir_acc = bt.get("directional_accuracy")
    dir_txt = f" It called the direction right {round(dir_acc)} times out of 100." if dir_acc is not None else ""
    n = bt["n_windows"]
    if mae < best * 0.97:
        return {"status": "better",
                "text": f"In {n} past tests on {name} {tfl} forecasts, the model was more accurate than simple guesses "
                        f"(its typical error was {gain:.0f}% smaller than assuming no change).{dir_txt} "
                        "It is still only a guide, not a promise."}
    if mae <= best * 1.03:
        return {"status": "same",
                "text": f"On {name} {tfl} forecasts the model did about as well as the simple guess "
                        f"\"{best_label}\" in {n} past tests, but not better.{dir_txt} Treat it as a rough guide."}
    return {"status": "worse",
            "text": f"On {name} {tfl} forecasts the model has not done better than simply assuming "
                    f"\"{best_label}\" in {n} past tests.{dir_txt} Treat it as a rough guide."}


def variates_text(check: dict | None, used: list[str]) -> str:
    extra = [v for v in used if v not in ("close",)]
    if not check:
        return (f"Extra inputs used: {', '.join(extra)} (not checked yet)." if extra
                else "Only this market's own prices are used.")
    if check.get("multi_tested") and not extra:
        return ("Related markets were tested as extra inputs but did not make past forecasts more accurate, "
                "so only this market's own prices are used.")
    if extra:
        return f"Extra inputs used: {', '.join(extra)} (they made past forecasts more accurate)."
    return "Only this market's own prices are used (no related markets were available)."


def accuracy_text(stats: dict, name: str, tf: str) -> str:
    n = stats.get("n", 0)
    tfl = TF_LABEL.get(tf, tf)
    if not n:
        return (f"No {name} {tfl} forecast has reached its end yet, so there is no live track record. "
                "Forecasts are checked automatically once their time has passed.")
    u = stats["units"]
    err = f"{stats['mae']:g} pips" if u == "pips" else f"{stats['mae']:g}%"
    naive = f"{stats['naive_mae']:g} pips" if u == "pips" else f"{stats['naive_mae']:g}%"
    s = f"Of the last {n} finished forecasts, "
    if stats.get("direction_n"):
        s += f"the direction was right {stats['direction_hits']} of {stats['direction_n']} times. "
    else:
        s += "none had a clear direction to check. "
    s += (f"Typical miss: {err} (assuming no change would have missed by {naive}). "
          f"The price stayed inside the middle range {stats['in50_pct']:g}% of the time (should be about 50%) "
          f"and inside the wide range {stats['in80_pct']:g}% of the time (should be about 80%).")
    if n < 20:
        s += " That is still a small sample, so don't read too much into it."
    return s


def agreement(fc_dir: str | None, plan: dict | None) -> dict:
    """Compare the forecast direction ('up'|'down'|'flat') with a plan/signal card."""
    if fc_dir is None:
        return {"status": "none", "text": "No forecast yet to compare with the trade plan."}
    if not plan or plan.get("action") not in ("BUY", "SELL", "WAIT"):
        return {"status": "none", "text": "No trade plan is available to compare with."}
    action = plan["action"]
    fc_words = {"up": "points up", "down": "points down", "flat": "shows no clear direction"}[fc_dir]
    if action == "WAIT":
        side = {"long": " (a possible buy is forming)", "short": " (a possible sell is forming)"}.get(
            plan.get("direction") or "", "")
        return {"status": "neutral",
                "text": f"The plan says WAIT{side}. The forecast {fc_words}; wait for the plan's conditions before acting."}
    want = "up" if action == "BUY" else "down"
    if fc_dir == "flat":
        return {"status": "neutral",
                "text": f"The forecast shows no clear direction, so it neither supports nor contradicts the {action} plan."}
    if fc_dir == want:
        return {"status": "agree", "text": f"The forecast agrees with the {action} plan."}
    return {"status": "disagree", "text": f"The forecast {fc_words} while the plan says {action} – be careful."}
