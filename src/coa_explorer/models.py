"""The model-adapter interface: the only thing the answer engine knows about a language model.

Messages and tool calls are provider-neutral. An adapter may attach an opaque `raw` payload to a
model turn (for example Gemini's content with its thought signatures); the engine hands it back
unchanged in the history so the adapter can replay it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON Schema for the arguments


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    id: str | None = None


@dataclass(frozen=True)
class ToolResult:
    call: ToolCall
    content: Any  # JSON-serialisable


@dataclass
class Message:
    role: Literal["user", "model", "tool"]
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    raw: Any = None


@dataclass
class ModelTurn:
    text: str | None
    tool_calls: list[ToolCall]
    raw: Any = None


class ModelAdapter(Protocol):
    def generate(
        self, system: str, messages: list[Message], tools: list[ToolSpec]
    ) -> ModelTurn: ...
