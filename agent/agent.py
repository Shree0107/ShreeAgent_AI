"""TradingAgent: wires the LLM provider, the system prompt and the analysis tools together."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from agent.llm.base import AgentResult, EventCallback, LLMProvider
from agent.prompts import SYSTEM_PROMPT
from agent.tools import TOOLS, execute_tool
from config.settings import get_settings

log = logging.getLogger(__name__)


def make_provider(name: str | None = None) -> LLMProvider:
    name = name or get_settings().llm_provider
    if name == "anthropic":
        from agent.llm.anthropic_llm import AnthropicLLM

        return AnthropicLLM()
    if name == "openai_compat":
        from agent.llm.openai_compat import OpenAICompatLLM

        return OpenAICompatLLM()
    raise ValueError(f"Unknown LLM_PROVIDER '{name}'")


class TradingAgent:
    def __init__(self, provider: LLMProvider | None = None, tools=None, executor=None):
        self.provider = provider or make_provider()
        self.tools = tools or TOOLS
        self.execute = executor or execute_tool

    def ask(
        self,
        question: str,
        history: list[dict] | None = None,
        deep: bool = False,
        on_event: EventCallback | None = None,
    ) -> AgentResult:
        """history: earlier turns as [{"role", "content"}] plain text. deep=True uses LLM_DEEP_MODEL."""
        s = get_settings()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC (%A)")
        # The date goes in the user turn, not the system prompt, so the system prompt stays cacheable.
        user = f"[Current time: {now}]\n{question}"
        prior = [{"role": m["role"], "content": m["content"]} for m in (history or []) if m.get("content")][-12:]
        while prior and prior[0]["role"] != "user":  # conversation must start with a user turn
            prior.pop(0)
        msgs = prior + [{"role": "user", "content": user}]
        model = s.llm_deep_model if deep else s.llm_model
        log.info("Agent question (%s): %s", model, question[:120])
        return self.provider.run(SYSTEM_PROMPT, msgs, self.tools, self.execute, model=model, on_event=on_event)
