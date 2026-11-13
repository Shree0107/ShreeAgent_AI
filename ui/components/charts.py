"""Plotly figures for the dashboard.

Colour roles (validated reference palette): series slots in fixed order, candle up/down as a
polarity pair, forecast = series-1 blue with a lighter band. Indicators sit in their own stacked
panels (one y-axis each). Never dual axes.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analysis import indicators as ind

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
UP, DOWN = "#1baf7a", "#e34948"
MUTED = "rgba(128,128,128,0.35)"
GRID = "rgba(128,128,128,0.15)"


def _layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.01, x=0), xaxis_rangeslider_visible=False,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def price_chart(
    df: pd.DataFrame,
    title: str,
    overlays: list[str] = ("ema_21", "ema_50", "ema_200"),
    show_bb: bool = True,
    show_vwap: bool = False,
    panels: list[str] = ("volume", "rsi", "macd"),
    levels: dict | None = None,
    has_volume: bool = True,
    bars: int = 300,
) -> go.Figure:
    d = ind.add_all(df, has_volume=has_volume, intraday=False).tail(bars)
    panels = [p for p in panels if not (p == "volume" and (not has_volume or d["volume"].sum() == 0))]
    rows = 1 + len(panels)
    heights = [0.55] + [0.45 / max(len(panels), 1)] * len(panels) if panels else [1.0]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=heights,
                        subplot_titles=[title] + [p.upper() for p in panels])

    fig.add_trace(go.Candlestick(
        x=d.index, open=d.open, high=d.high, low=d.low, close=d.close, name="Price",
        increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN, width=1), fillcolor=DOWN)), row=1, col=1)

    for i, col in enumerate(overlays):
        if col in d:
            fig.add_trace(go.Scatter(x=d.index, y=d[col], name=col.upper().replace("_", " "),
                                     line=dict(color=SERIES[[0, 1, 6, 3][i % 4]], width=1.5)), row=1, col=1)
    if show_bb and "bb_upper" in d:
        fig.add_trace(go.Scatter(x=d.index, y=d.bb_upper, name="BB upper", line=dict(color=MUTED, width=1, dash="dot")), row=1, col=1)
        fig.add_trace(go.Scatter(x=d.index, y=d.bb_lower, name="BB lower", line=dict(color=MUTED, width=1, dash="dot"),
                                 fill="tonexty", fillcolor="rgba(128,128,128,0.06)"), row=1, col=1)
    if show_vwap and "vwap" in d:
        fig.add_trace(go.Scatter(x=d.index, y=d.vwap, name="VWAP", line=dict(color=SERIES[4], width=1.5)), row=1, col=1)

    for lvl in (levels or {}).get("supports", []):
        fig.add_hline(y=lvl["price"], line=dict(color=UP, width=1, dash="dash"), opacity=0.7, row=1, col=1,
                      annotation_text=f"S {lvl['price']:g}", annotation_position="bottom right")
    for lvl in (levels or {}).get("resistances", []):
        fig.add_hline(y=lvl["price"], line=dict(color=DOWN, width=1, dash="dash"), opacity=0.7, row=1, col=1,
                      annotation_text=f"R {lvl['price']:g}", annotation_position="top right")

    for r, p in enumerate(panels, start=2):
        if p == "volume":
            colors = [UP if c >= o else DOWN for c, o in zip(d.close, d.open)]
            fig.add_trace(go.Bar(x=d.index, y=d.volume, name="Volume", marker_color=colors, opacity=0.6,
                                 showlegend=False), row=r, col=1)
        elif p == "rsi":
            fig.add_trace(go.Scatter(x=d.index, y=d.rsi_14, name="RSI 14", line=dict(color=SERIES[6], width=1.5),
                                     showlegend=False), row=r, col=1)
            for y in (70, 30):
                fig.add_hline(y=y, line=dict(color=MUTED, width=1, dash="dot"), row=r, col=1)
            fig.update_yaxes(range=[0, 100], row=r, col=1)
        elif p == "macd":
            fig.add_trace(go.Bar(x=d.index, y=d.macd_hist, name="MACD hist", showlegend=False,
                                 marker_color=[UP if v >= 0 else DOWN for v in d.macd_hist.fillna(0)]), row=r, col=1)
            fig.add_trace(go.Scatter(x=d.index, y=d.macd, name="MACD", line=dict(color=SERIES[0], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=d.index, y=d.macd_signal, name="Signal", line=dict(color=SERIES[1], width=1.5)), row=r, col=1)
        elif p == "stoch":
            fig.add_trace(go.Scatter(x=d.index, y=d.stoch_k, name="%K", line=dict(color=SERIES[0], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=d.index, y=d.stoch_d, name="%D", line=dict(color=SERIES[1], width=1.5)), row=r, col=1)
            fig.update_yaxes(range=[0, 100], row=r, col=1)
        elif p == "adx":
            fig.add_trace(go.Scatter(x=d.index, y=d.adx, name="ADX", line=dict(color=SERIES[6], width=1.5)), row=r, col=1)
            fig.add_trace(go.Scatter(x=d.index, y=d.plus_di, name="+DI", line=dict(color=UP, width=1)), row=r, col=1)
            fig.add_trace(go.Scatter(x=d.index, y=d.minus_di, name="-DI", line=dict(color=DOWN, width=1)), row=r, col=1)
        elif p == "atr":
            fig.add_trace(go.Scatter(x=d.index, y=d.atr_14, name="ATR 14", line=dict(color=SERIES[0], width=1.5),
                                     showlegend=False), row=r, col=1)
    # Remove weekend gaps for daily stock/FX charts
    if len(d) > 2 and (d.index[1] - d.index[0]) >= pd.Timedelta(days=1):
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    return _layout(fig, 380 + 170 * len(panels))


def forecast_chart(df: pd.DataFrame, fc: dict, history_bars: int = 150) -> go.Figure:
    hist = df.tail(history_bars)
    x = pd.to_datetime(fc["dates"])
    # Join the forecast to the last actual bar so the bands start at the current price.
    x0 = [hist.index[-1]] + list(x)
    last = fc["last_close"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hist.index, y=hist.close, name="Actual close", line=dict(color="#8a8984", width=1.5)))
    fig.add_trace(go.Scatter(x=x0, y=[last] + fc["q90"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x0, y=[last] + fc["q10"], name="10–90% band", fill="tonexty",
                             fillcolor="rgba(42,120,214,0.15)", line=dict(width=0)))
    fig.add_trace(go.Scatter(x=x0, y=[last] + fc["q75"], line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x0, y=[last] + fc["q25"], name="25–75% band", fill="tonexty",
                             fillcolor="rgba(42,120,214,0.30)", line=dict(width=0)))
    fig.add_trace(go.Scatter(x=x0, y=[last] + fc["median"], name="Median forecast",
                             line=dict(color=SERIES[0], width=2), mode="lines+markers", marker=dict(size=5)))
    fig.update_layout(title=f"{fc['symbol']} | TimesFM-3 forecast ({fc['horizon']} × {fc['timeframe']})")
    return _layout(fig, 460)


def signal_chart(df: pd.DataFrame, card: dict, bars: int = 120) -> go.Figure:
    """Daily candles with the signal's entry zone, stop loss and targets drawn on."""
    d = df.tail(bars)
    fig = go.Figure(go.Candlestick(
        x=d.index, open=d.open, high=d.high, low=d.low, close=d.close, name="Price",
        increasing=dict(line=dict(color=UP, width=1), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN, width=1), fillcolor=DOWN)))
    lv = card.get("levels") or {}
    if lv:
        lo, hi = sorted((lv["entry_low"], lv["entry_high"]))
        fig.add_hrect(y0=lo, y1=hi, fillcolor=SERIES[0], opacity=0.15, line_width=0,
                      annotation_text="Entry zone", annotation_position="top left")
        fig.add_hline(y=lv["stop"], line=dict(color=DOWN, width=2, dash="dash"),
                      annotation_text=f"Stop {lv['stop']:g}", annotation_position="bottom right")
        for i, k in enumerate(("target1", "target2"), start=1):
            fig.add_hline(y=lv[k], line=dict(color=UP, width=2 if i == 1 else 1, dash="dash"),
                          annotation_text=f"Target {i} {lv[k]:g}", annotation_position="top right")
    if len(d) > 2 and (d.index[1] - d.index[0]) >= pd.Timedelta(days=1):
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    fig.update_layout(title=f"{card['symbol']} · daily · {card['action']}" + ("" if lv else " (levels shown when BUY/SELL)"))
    return _layout(fig, 420)


def score_bar(components: dict[str, float]) -> go.Figure:
    names = list(components)
    vals = [components[n] for n in names]
    fig = go.Figure(go.Bar(x=vals, y=names, orientation="h", marker_color=[UP if v >= 0 else DOWN for v in vals],
                           text=[f"{v:+.0f}" for v in vals], textposition="outside"))
    fig.update_xaxes(range=[-100, 100], zeroline=True, zerolinecolor=MUTED)
    return _layout(fig, 60 + 40 * len(names))
