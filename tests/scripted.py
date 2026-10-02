"""A scripted model adapter: replays prepared turns so Seam 3 tests never call a real model."""

from __future__ import annotations

from collections.abc import Callable

from coa_explorer.models import Message, ModelTurn, ToolCall, ToolSpec

Turn = ModelTurn | Callable[[list[Message]], ModelTurn]


class ScriptedAdapter:
    def __init__(self, *turns: Turn):
        self._turns = list(turns)
        self.requests: list[tuple[str, list[Message], list[ToolSpec]]] = []

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        self.requests.append((system, list(messages), list(tools)))
        if not self._turns:
            raise AssertionError("the scripted adapter ran out of turns")
        turn = self._turns.pop(0)
        return turn(messages) if callable(turn) else turn


def search(query: str, **args) -> ModelTurn:
    return ModelTurn(text=None, tool_calls=[ToolCall("search", {"query": query, **args})])


def submit(
    summary: str, key_points: list[dict], covered: bool = True, message: str = ""
) -> ModelTurn:
    args = {
        "covered": covered,
        "summary": summary,
        "key_points": key_points,
        "not_covered_message": message,
    }
    return ModelTurn(text=None, tool_calls=[ToolCall("submit_answer", args)])


def submit_with_city(summary: str, key_points: list[dict], city_said: list[dict]) -> ModelTurn:
    args = {
        "covered": True,
        "summary": summary,
        "key_points": key_points,
        "city_said": city_said,
    }
    return ModelTurn(text=None, tool_calls=[ToolCall("submit_answer", args)])


def say(text: str) -> ModelTurn:
    return ModelTurn(text=text, tool_calls=[])


def point(text: str, *sources: str) -> dict:
    return {"text": text, "sources": list(sources)}
