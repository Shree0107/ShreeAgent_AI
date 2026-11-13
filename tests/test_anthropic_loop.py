"""AnthropicLLM tool loop against a fake client (no network, no key)."""
from types import SimpleNamespace as NS

from agent.llm.anthropic_llm import AnthropicLLM
from agent.tools import TOOLS


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return NS(stop_reason="tool_use", model="m", content=[
                NS(type="thinking", thinking=""),
                NS(type="tool_use", id="t1", name="resolve_symbol", input={"query": "EUR/USD"}),
                NS(type="tool_use", id="t2", name="get_quote", input={}),  # missing arg -> is_error
            ])
        return NS(stop_reason="end_turn", model="m", content=[NS(type="text", text="Final report")])


def test_anthropic_tool_loop():
    llm = AnthropicLLM(api_key="test")
    fake = FakeMessages()
    llm.client = NS(beta=NS(messages=fake))
    from agent.tools import execute_tool

    res = llm.run("sys", [{"role": "user", "content": "hi"}], TOOLS, execute_tool, model="claude-sonnet-5-5")
    assert res.text == "Final report" and len(res.tool_calls) == 2
    first, second = fake.calls
    assert first["fallbacks"] == "default" and first["thinking"] == {"type": "adaptive"}
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    # Turn 2 must contain: the user msg, the assistant turn unchanged, then ONE user msg with both results
    msgs = second["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    results = msgs[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert results[0]["is_error"] is False and results[1]["is_error"] is True


def test_refusal_is_handled():
    llm = AnthropicLLM(api_key="test")
    llm.client = NS(beta=NS(messages=NS(create=lambda **kw: NS(stop_reason="refusal", model="m", content=[]))))
    res = llm.run("sys", [{"role": "user", "content": "x"}], TOOLS, lambda n, a: ("", False))
    assert res.stop_reason == "refusal" and "declined" in res.text
