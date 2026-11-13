from analysis.combined import full_analysis
from analysis.fundamental import evaluate
from analysis.macro_fx import analyse_fx
from analysis.sentiment import analyse_news, lexicon_score
from analysis.trade_plan import build_plan
from data.symbols import parse_symbol
from tests.conftest import FakeData


def test_strong_stock_fundamentals_bullish():
    sym = parse_symbol("AAPL")
    rep = evaluate(sym, FakeData().get_fundamentals(sym).data)
    assert rep.bias == "bullish" and rep.strengths
    assert rep.valuation["sector_pe"] == 28.0


def test_indian_sector_benchmark_premium():
    rep = evaluate(parse_symbol("TCS.NS"), {"sector": "Technology", "pe_trailing": 30.0})
    assert rep.valuation["sector_pe"] == round(28 * 1.3, 1)


def test_fx_rate_differential_favours_higher_rate():
    rep = analyse_fx(parse_symbol("EUR/USD"), data=FakeData())
    # USD 5.0% vs EUR 2.0% (and ECB cutting): fundamentals favour USD, so EUR/USD bearish
    assert rep.rate_differential == -3.0
    assert rep.bias == "bearish"
    assert rep.events and rep.events[0]["title"] == "US CPI"


def test_long_plan_levels_ordered():
    p = build_plan("bullish", price=100, atr=2, supports=[97, 94], resistances=[105, 110])
    assert p.direction == "long"
    assert p.stop_loss < p.entry_zone[0] <= p.entry_zone[1] < p.take_profits[0] < p.take_profits[1]
    assert all(rr > 0 for rr in p.risk_reward)


def test_short_plan_and_neutral():
    p = build_plan("bearish", price=100, atr=2, supports=[95], resistances=[101.5])
    assert p.direction == "short" and p.stop_loss > p.entry_zone[1] > p.take_profits[0]
    n = build_plan("neutral", 100, 2, [97], [103])
    assert n.direction == "none" and any("103" in x for x in n.notes)


def test_sentiment_lexicon_and_report():
    assert lexicon_score("Shares surge after earnings beat") > 0
    assert lexicon_score("Stock plunges on fraud probe") < 0
    rep = analyse_news(parse_symbol("AAPL"), data=FakeData())
    assert rep.label == "positive" and rep.n_articles == 2 and rep.method == "lexicon"


def test_confidence_needs_two_agreeing_components():
    from analysis.combined import confidence

    assert confidence({"technical": 80}, "aligned", 80)[0] == "Medium"
    assert confidence({"technical": 80, "fundamental": 60}, "aligned", 70)[0] == "High"
    assert confidence({"technical": 80, "fundamental": -60}, "aligned", 25)[0] != "High"


def test_fx_without_macro_data_excluded_from_combined():
    class NoMacro(FakeData):
        def get_macro_series(self, series_id):
            raise RuntimeError("no key")

    a = full_analysis(parse_symbol("EUR/USD"), "1d", 5, include_forecast=False, data=NoMacro())
    assert "fundamental" not in a["combined"]["components"]
    assert a["fundamental"]["n_factors"] == 0


def test_full_analysis_end_to_end_offline():
    a = full_analysis(parse_symbol("AAPL"), "1d", 5, data=FakeData(drift=0.003))
    assert set(a["combined"]) >= {"score", "bias", "confidence"}
    assert a["combined"]["confidence"] in ("High", "Medium", "Low")
    assert "forecast" in a and len(a["forecast"]["median"]) == 2  # compact
    assert a["investing_url"].startswith("https://www.investing.com/")
    assert "not financial advice" in a["disclaimer"]
