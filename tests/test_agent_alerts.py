import json

from agent.agent import TradingAgent
from agent.llm.base import AgentResult, LLMProvider, ToolCall
from agent.report import analysis_to_markdown, markdown_to_pdf
from agent.tools import TOOLS, execute_tool, to_json
from alerts.scanner import ScanRow, format_digest
from alerts.whatsapp import CallMeBotNotifier, split_message
from analysis.combined import full_analysis
from data.symbols import parse_symbol
from tests.conftest import FakeData


class ScriptedLLM(LLMProvider):
    """Fake provider: calls one tool, then answers using its output."""

    def __init__(self):
        self.seen = None

    def run(self, system, messages, tools, execute, model=None, max_steps=12, on_event=None):
        self.seen = (system, messages, [t.name for t in tools])
        out, err = execute("resolve_symbol", {"query": "EUR/USD"})
        return AgentResult(f"done: {json.loads(out)['candidates'][0]['ticker']}",
                           [ToolCall("resolve_symbol", {"query": "EUR/USD"}, not err)], "fake", "end_turn")


def test_tool_schemas_valid():
    names = [t.name for t in TOOLS]
    assert len(names) == len(set(names)) and "full_analysis" in names
    for t in TOOLS:
        s = t.input_schema
        assert s["type"] == "object" and set(s["required"]) <= set(s["properties"])
        assert len(t.description) > 20


def test_execute_tool_errors_are_returned_not_raised():
    out, err = execute_tool("nope", {})
    assert err
    out, err = execute_tool("get_quote", {})
    assert err and "Missing" in out


def test_agent_passes_history_and_date():
    llm = ScriptedLLM()
    hist = [{"role": "assistant", "content": "orphan"}, {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"}]
    res = TradingAgent(provider=llm).ask("Analyse EUR/USD", hist)
    system, msgs, tool_names = llm.seen
    assert res.text == "done: EUR/USD"
    assert msgs[0]["role"] == "user"  # leading assistant turn dropped
    assert "[Current time:" in msgs[-1]["content"] and "Analyse EUR/USD" in msgs[-1]["content"]
    assert "not financial advice" in system.lower() and "full_analysis" in tool_names


def test_report_markdown_and_pdf():
    a = full_analysis(parse_symbol("AAPL"), "1d", 5, data=FakeData(drift=0.003))
    md = analysis_to_markdown(a)
    assert md.startswith("# AAPL") and "Investing.com" in md and "not financial advice" in md
    pdf = markdown_to_pdf(md)
    assert pdf[:4] == b"%PDF" and len(pdf) > 1000
    assert to_json({"x": float("nan")}) is not None


def test_whatsapp_split_and_callmebot(monkeypatch):
    chunks = split_message("\n".join(["line " * 50] * 20), limit=500)
    assert all(len(c) <= 500 for c in chunks) and len(chunks) > 1
    sent = []

    class R:
        status_code, text = 200, "Message queued"

    monkeypatch.setattr("alerts.whatsapp.requests.get", lambda url, params, timeout: sent.append(params) or R())
    assert CallMeBotNotifier("+910000000000", "key").send("hello")
    assert sent[0]["text"] == "hello" and sent[0]["phone"] == "+910000000000"


def test_digest_format():
    rows = [ScanRow("EUR/USD", 1.08, 45, "bullish", "Medium", "neutral", 55, {
        "direction": "long", "entry_zone": (1.079, 1.08), "stop_loss": 1.075, "take_profits": [1.09, 1.1],
        "risk_reward": [2.0, 4.0]}, ["strong bullish", "bias changed neutral→bullish"])]
    msg = format_digest(rows)
    assert "EUR/USD" in msg and "SL 1.075" in msg and "not financial advice" in msg
