"""Claude via the official Anthropic SDK, using a manual tool-use loop."""
from __future__ import annotations

import logging

import anthropic

from agent.llm.base import AgentResult, EventCallback, LLMProvider, ToolCall, ToolExecutor, ToolSpec
from config.settings import get_settings

log = logging.getLogger(__name__)

# Server-side refusal fallback: if the model declines (safety classifier false positive),
# the API re-runs the request on a fallback model inside the same call.
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM(LLMProvider):
    def __init__(self, api_key: str | None = None):
        s = get_settings()
        key = api_key or s.anthropic_api_key or None  # None -> SDK reads env / `ant auth` profile
        self.client = anthropic.Anthropic(api_key=key, max_retries=3)
        self.settings = s

    def run(self, system, messages, tools, execute: ToolExecutor, model=None, max_steps=12,
            on_event: EventCallback | None = None) -> AgentResult:
        s = self.settings
        model = model or s.llm_model
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        # Prior turns are plain text. This turn's tool calls stay in `msgs` until it ends.
        msgs: list[dict] = [dict(m) for m in messages]
        calls: list[ToolCall] = []
        stop = ""

        for _ in range(max_steps):
            try:
                resp = self.client.beta.messages.create(
                    model=model,
                    max_tokens=s.llm_max_tokens,
                    # System prompt is static, so it gets cached across turns.
                    system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                    tools=tool_defs,
                    messages=msgs,
                    thinking={"type": "adaptive"},
                    output_config={"effort": s.llm_effort},
                    betas=[_FALLBACK_BETA],
                    fallbacks="default",
                )
            except anthropic.AuthenticationError as e:
                raise RuntimeError("Anthropic API key is invalid or missing. Set ANTHROPIC_API_KEY in .env") from e
            except anthropic.RateLimitError as e:
                raise RuntimeError("Anthropic rate limit reached. Wait a minute and try again.") from e
            except anthropic.BadRequestError as e:
                raise RuntimeError(f"Anthropic API rejected the request: {e.message}") from e
            except anthropic.APIConnectionError as e:
                raise RuntimeError("Could not reach the Anthropic API. Check your internet connection.") from e

            stop = resp.stop_reason or ""
            if stop == "refusal":
                return AgentResult("The model declined this request. Try rephrasing it.", calls, model, stop)
            if stop == "pause_turn":
                msgs.append({"role": "assistant", "content": resp.content})
                continue

            tool_uses = [b for b in resp.content if b.type == "tool_use"]
            if stop != "tool_use" or not tool_uses:
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                if stop == "max_tokens":
                    text += "\n\n_(Response truncated: increase LLM_MAX_TOKENS in .env.)_"
                return AgentResult(text, calls, resp.model, stop)

            # Append the full assistant turn (incl. thinking blocks) unchanged, then all results in ONE user message.
            msgs.append({"role": "assistant", "content": resp.content})
            results = []
            for tu in tool_uses:
                if on_event:
                    on_event("tool_start", {"name": tu.name, "input": tu.input})
                out, is_err = execute(tu.name, dict(tu.input or {}))
                calls.append(ToolCall(tu.name, dict(tu.input or {}), not is_err, out[:300]))
                if on_event:
                    on_event("tool_end", {"name": tu.name, "ok": not is_err})
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": out, "is_error": is_err})
            msgs.append({"role": "user", "content": results})

        return AgentResult("Stopped: too many tool steps. Try a more specific question.", calls, model, "max_steps")
