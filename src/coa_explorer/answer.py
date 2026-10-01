"""The answer engine: a tool-using loop that turns a question into a cited Answer.

The model may call `search` over the index, then must finish with `submit_answer`. The model cites
by piece id; the Citation text comes from the index, never from the model, and a key point may only
cite pieces the model actually retrieved. Key points left without a Citation are removed, and an
answer left with none is reported as not covered.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field

from coa_explorer.models import Message, ModelAdapter, ToolCall, ToolResult, ToolSpec
from coa_explorer.search import Index, Piece

MAX_SUMMARY_CHARS = 600
MAX_KEY_POINTS = 6
MAX_KEY_POINT_CHARS = 500
MAX_NOT_COVERED_CHARS = 400
MAX_PIECE_CHARS_TO_MODEL = 2500
NOT_COVERED_DEFAULT = (
    "The Annual Audit Reports I have don't cover that, or I couldn't ground an answer in them."
)

SYSTEM_PROMPT = """\
You answer questions about the Commission on Audit's (COA) Annual Audit Reports (AARs) on the \
City of Manila, 2020-2024, for ordinary residents, journalists and students. Today only Part II \
(Audit Observations and Recommendations) is searchable.

How to work
- Call `search` to find passages. Search again with different words, or a year or observation \
number filter, if the first results miss. Then call `submit_answer` exactly once to finish.
- Answer ONLY from passages `search` returned. Never use outside knowledge, never guess, never \
calculate or infer figures that the passages do not state. If the passages do not address the \
question, submit with covered=false and say so plainly; suggest what the reports do cover if you \
can. Questions about other cities, news, politics or people are out of scope: covered=false.
- Write in plain language, in English. Keep it short: a summary of 1-3 sentences, then at most \
five key points.
- Every key point must list the `id`s of the passages that support it in `sources`. A key point \
without sources will be deleted.

Wording
- An Audit Observation is a deficiency, non-compliance or weakness COA found. It is NOT a finding \
of fraud, corruption or wrongdoing. Never use words such as "fraud", "corruption", "stole", \
"illegal" or "misused" unless the passage itself uses them, and never describe a matter more \
strongly than the report does.
- Say "COA observed" or "COA recommended", not "COA found the City guilty". Refer to the audited \
agency as "the City of Manila".
- Management's response is Management Comment; COA's reply is the Auditor's Rejoinder. If a \
passage records one, present it fairly and attribute it to Management.
"""

SEARCH_TOOL = ToolSpec(
    name="search",
    description=(
        "Keyword search over the Part II Audit Observations of COA's Annual Audit Reports on the "
        "City of Manila. Returns ranked passages, each with an `id` and its `citation`."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Words to look for; may be empty if an observation number is given.",
            },
            "years": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Restrict to these AAR years (2020-2024).",
            },
            "observation": {
                "type": "integer",
                "description": "Restrict to this Audit Observation number.",
            },
        },
        "required": ["query"],
    },
)

SUBMIT_TOOL = ToolSpec(
    name="submit_answer",
    description="Finish: submit the final answer. Call exactly once.",
    parameters={
        "type": "object",
        "properties": {
            "covered": {
                "type": "boolean",
                "description": "False if the passages do not address the question.",
            },
            "summary": {"type": "string", "description": "1-3 sentence plain-language summary."},
            "key_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "sources": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "ids of the supporting passages returned by search.",
                        },
                    },
                    "required": ["text", "sources"],
                },
            },
            "not_covered_message": {
                "type": "string",
                "description": "When covered is false: say so plainly.",
            },
        },
        "required": ["covered"],
    },
)


class Citation(BaseModel):
    text: str = Field(
        description="COA's format, e.g. 'CY 2023 AAR, Part II, Observation No. 5, p. 71'"
    )
    title: str = Field(description="Title of the Audit Observation")


class KeyPoint(BaseModel):
    text: str = Field(max_length=MAX_KEY_POINT_CHARS)
    citations: list[Citation] = Field(min_length=1)


class Answer(BaseModel):
    type: Literal["answer"] = "answer"
    summary: str = Field(max_length=MAX_SUMMARY_CHARS)
    key_points: list[KeyPoint] = Field(min_length=1, max_length=MAX_KEY_POINTS)


class NotCovered(BaseModel):
    type: Literal["not_covered"] = "not_covered"
    message: str


class Status(BaseModel):
    type: Literal["status"] = "status"
    message: str


Event = Status | Answer | NotCovered


class AnswerEngine:
    def __init__(self, adapter: ModelAdapter, index: Index, max_search_rounds: int = 4):
        self._adapter = adapter
        self._index = index
        self._max_search_rounds = max_search_rounds

    def ask(self, question: str) -> Iterator[Event]:
        """Yield `Status` updates while working, then exactly one `Answer` or `NotCovered`."""
        messages = [Message(role="user", text=question)]
        seen: dict[str, Piece] = {}
        nudged = False
        for round_number in range(self._max_search_rounds + 1):
            last_round = round_number == self._max_search_rounds
            tools = [SUBMIT_TOOL] if last_round else [SEARCH_TOOL, SUBMIT_TOOL]
            turn = self._adapter.generate(SYSTEM_PROMPT, messages, tools)
            messages.append(
                Message(role="model", text=turn.text, tool_calls=turn.tool_calls, raw=turn.raw)
            )
            if not turn.tool_calls:
                if nudged or last_round:
                    break
                nudged = True
                messages.append(Message(role="user", text="Finish by calling submit_answer."))
                continue
            results = []
            for call in turn.tool_calls:
                if call.name == "submit_answer":
                    yield finalise(call.args, seen)
                    return
                if call.name == "search" and not last_round:
                    yield Status(
                        message=f"Searching the reports for “{call.args.get('query', '')}”"
                    )
                    try:
                        results.append(ToolResult(call, self._run_search(call, seen)))
                    except (TypeError, ValueError):
                        # Tell the model what was wrong so it can retry, instead of failing.
                        error = {
                            "error": "years must be a list of integers; observation an integer"
                        }
                        results.append(ToolResult(call, error))
                else:
                    results.append(ToolResult(call, {"error": f"unknown tool {call.name}"}))
            messages.append(Message(role="tool", tool_results=results))
        yield NotCovered(message=NOT_COVERED_DEFAULT)

    def _run_search(self, call: ToolCall, seen: dict[str, Piece]) -> list[dict]:
        args = call.args
        observation = args.get("observation")
        pieces = self._index.search(
            str(args.get("query", "")),
            years=[int(year) for year in args.get("years") or []] or None,
            observation=int(observation) if observation is not None else None,
        )
        for piece in pieces:
            seen[piece.key] = piece
        return [
            {
                "id": piece.key,
                "citation": piece.citation,
                "title": piece.title,
                "kind": piece.kind,
                "text": piece.text[:MAX_PIECE_CHARS_TO_MODEL],
            }
            for piece in pieces
        ]


def finalise(args: dict, seen: dict[str, Piece]) -> Answer | NotCovered:
    """Validate the model's submitted answer against what it retrieved."""
    if args.get("covered") is not True:
        message = clip(str(args.get("not_covered_message") or ""), MAX_NOT_COVERED_CHARS)
        return NotCovered(message=message or NOT_COVERED_DEFAULT)
    key_points = []
    for raw in args.get("key_points") or []:
        citations: dict[str, Citation] = {}
        sources = raw.get("sources") or []
        for source in [sources] if isinstance(sources, str) else sources:
            piece = seen.get(source)
            if piece:
                citations.setdefault(
                    piece.citation, Citation(text=piece.citation, title=piece.title)
                )
        text = clip(str(raw.get("text") or ""), MAX_KEY_POINT_CHARS)
        if text and citations:
            key_points.append(KeyPoint(text=text, citations=list(citations.values())))
    if not key_points:
        return NotCovered(message=NOT_COVERED_DEFAULT)
    summary = clip(str(args.get("summary") or ""), MAX_SUMMARY_CHARS)
    return Answer(summary=summary, key_points=key_points[:MAX_KEY_POINTS])


def clip(text: str, limit: int) -> str:
    """Trim to `limit` characters at a word boundary, marking the cut."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
