"""Provider-neutral LLM interface. Each provider runs its own tool-use loop."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., Any]


@dataclass
class ToolCall:
    name: str
    input: dict
    ok: bool
    output_preview: str = ""


@dataclass
class AgentResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    stop_reason: str = ""


# execute(name, input) -> (result_text, is_error)
ToolExecutor = Callable[[str, dict], tuple[str, bool]]
# on_event(kind, payload): lets the UI show progress ("tool", {...}) while the agent works
EventCallback = Callable[[str, dict], None]


class LLMProvider(ABC):
    @abstractmethod
    def run(
        self,
        system: str,
        messages: list[dict],
        tools: list[ToolSpec],
        execute: ToolExecutor,
        model: str | None = None,
        max_steps: int = 12,
        on_event: EventCallback | None = None,
    ) -> AgentResult:
        """messages: prior turns as [{"role": "user"|"assistant", "content": str}], ending with the new user turn."""
