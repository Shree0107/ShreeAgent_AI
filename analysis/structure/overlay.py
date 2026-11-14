"""One call that runs every detector and returns chart-ready JSON for the 'AI analysis' overlay."""
from __future__ import annotations

import pandas as pd

from analysis.structure import liquidity as liq
from analysis.structure.lines import channels, trendlines
from analysis.structure.market import fibonacci, label_swings, structure_events, trend_from_labels
from analysis.structure.patterns_chart import chart_patterns, divergences, regime
from analysis.structure.swings import zigzag
from analysis.structure.zones import fair_value_gaps, order_blocks, sr_zones, supply_demand

MAX_BARS = 800


def build_overlay(df: pd.DataFrame, is_fx: bool = True, swing_mult: float = 2.0) -> dict:
    d = df.tail(MAX_BARS)
    if len(d) < 30:
        return {"error": "Not enough candles for the analysis overlay"}
    swings = label_swings(zigzag(d, swing_mult))
    events, structure_trend = structure_events(d, swings)
    lines = trendlines(d, swings)
    levels = liq.session_levels(d) + liq.equal_levels(d, swings) + liq.round_numbers(float(d.close.iloc[-1]), is_fx)
    out = {
        "bars": len(d),
        "swings": [s.as_dict() for s in swings[-30:]],
        "structure": {"trend": structure_trend, "swing_trend": trend_from_labels(swings),
                      "events": [e.as_dict() for e in events[-8:]]},
        "trendlines": [ln.as_dict() for ln in lines],
        "channels": [c.as_dict() for c in channels(d, swings, lines)],
        "zones": [z.as_dict() for z in sr_zones(d, swings)],
        "supply_demand": [z.as_dict() for z in supply_demand(d) if z.status == "fresh"],
        "order_blocks": [z.as_dict() for z in order_blocks(d, swings) if z.status == "fresh"],
        "fvgs": [z.as_dict() for z in fair_value_gaps(d)],
        "fibonacci": fibonacci(d, swings),
        "liquidity": [lv.as_dict() for lv in levels],
        "sweeps": [s.as_dict() for s in liq.sweeps(d, levels)[-5:]],
        "patterns": [p.as_dict() for p in chart_patterns(d, swings)],
        "divergences": divergences(d, swings),
        "regime": regime(d),
    }
    return out
