"""Optional provider for any OpenAI-compatible chat API (e.g. a local model server).

Requires `pip install openai`. Set LLM_PROVIDER=openai_compat, OPENAI_BASE_URL, OPENAI_API_KEY, LLM_MODEL.
"""
from __future__ import annotations

import json

from agent.llm.base import AgentResult, LLMProvider, ToolCall
from config.settings import get_settings


class OpenAICompatLLM(LLMProvider):
    def __init__(self):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("Install the 'openai' package to use LLM_PROVIDER=openai_compat") from e
        s = get_settings()
        self.client = OpenAI(api_key=s.openai_api_key or "none", base_url=s.openai_base_url or None)
        self.settings = s

    def run(self, system, messages, tools, execute, model=None, max_steps=12, on_event=None) -> AgentResult:
        model = model or self.settings.llm_model
        tool_defs = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                       "parameters": t.input_schema}} for t in tools]
        msgs = [{"role": "system", "content": system}] + [dict(m) for m in messages]
        calls: list[ToolCall] = []
        for _ in range(max_steps):
            resp = self.client.chat.completions.create(model=model, messages=msgs, tools=tool_defs)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return AgentResult(msg.content or "", calls, model, resp.choices[0].finish_reason or "")
            msgs.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                if on_event:
                    on_event("tool_start", {"name": tc.function.name, "input": args})
                out, is_err = execute(tc.function.name, args)
                calls.append(ToolCall(tc.function.name, args, not is_err, out[:300]))
                if on_event:
                    on_event("tool_end", {"name": tc.function.name, "ok": not is_err})
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        return AgentResult("Stopped: too many tool steps.", calls, model, "max_steps")
