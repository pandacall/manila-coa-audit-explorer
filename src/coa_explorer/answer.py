"""The answer engine: a tool-using loop that turns a question into a cited Answer.

The model may call `search` and `timeline` over the index, then must finish with `submit_answer`.
An answer can carry "What the City said" (Management Comment or Reported Status), cited like key
points and shown apart from them. The model cites by piece id; the Citation text comes from the
index, never from the model, and a key point may only cite pieces the model actually retrieved. Key
points left without a Citation are removed, and an answer left with none is reported as not
covered. A timeline shown with an answer is the one the `timeline` tool returned, not anything the
model wrote.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, Field

from coa_explorer.models import Message, ModelAdapter, ToolCall, ToolResult, ToolSpec
from coa_explorer.search import DEFAULT_LIMIT, Index, Piece
from coa_explorer.timeline import Timeline

MAX_SUMMARY_CHARS = 600
MAX_KEY_POINTS = 6
MAX_CITY_SAID = 4
MAX_TIMELINES = 3
MAX_SEARCH_RESULTS = 25
MAX_KEY_POINT_CHARS = 500
MAX_NOT_COVERED_CHARS = 400
MAX_PIECE_CHARS_TO_MODEL = 2500
NOT_COVERED_DEFAULT = (
    "The Annual Audit Reports I have don't cover that, or I couldn't ground an answer in them."
)

SYSTEM_PROMPT = """\
You answer questions about the Commission on Audit's (COA) Annual Audit Reports (AARs) on the \
City of Manila, 2020-2024, for ordinary residents, journalists and students. Part II holds each \
year's Audit Observations and Recommendations. Part III holds, for each AAR, COA's Status of \
Implementation of Prior Years' Recommendations (Implemented, Partially Implemented or Not \
Implemented), with Management's action and the reason given for partial or non-implementation. \
For 2023 and 2024 there are two more documents: the AAPSI (part "AAPSI") is Management's own \
report of its Action Plan for each Recommendation, with the person or department responsible, \
target dates and the Reported Status Management claims; the APMT (part "APMT") is COA's \
validation of it, with COA's own Status of Implementation.

How to work
- Call `search` to find passages. Search again with different words, or a year or observation \
number filter, if the first results miss. Do not repeat a query that already returned results. \
You have a limited number of searches: to compare years, search each year with the `years` \
filter. Then call `submit_answer` exactly once to finish.
- `search` understands both COA's exact words and everyday language. Each Part II hit comes back \
as the whole Audit Observation (description, recommendations, Management Comment, Auditor's \
Rejoinder); `matched` marks the passages that matched your query. To read a specific observation, \
such as "2023 Observation No. 5", search with an empty query and `years` and `observation` set.
- With no `years` filter, results span all years, newest first, but a search returns at most five \
observations, so a topic that may span many years needs a search per year to be sure. When a topic \
appears in several years, say which years in your summary, going by the citations of the passages \
you used.
- To find out whether Manila acted on a recommendation, find the observation with `search`, then \
call `timeline` with the `origin_year` and `origin_observation` printed on its results. It returns \
when the observation was raised and COA's Status of Implementation in each later AAR, each step \
with its own `id` and citation. Observations raised before 2020 have a timeline too, cited to the \
AAR that tracks them. A step can also hold the AAPSI's `action_plans` (Management's account) and \
the APMT's `validations` (COA's Status of Implementation). To review one year's backlog, `search` \
with `parts` ["III"], that `years` filter and a `status`, and raise `limit`.
- Answer ONLY from passages `search` and `timeline` returned. Never use outside knowledge, never \
guess, never calculate or infer figures that the passages do not state. If the passages do not \
address the question, submit with covered=false and say so plainly; suggest what the reports do \
cover if you can. Questions about other cities, news, politics or people are out of scope: \
covered=false.
- Write in plain language, in English. Keep it short: a summary of 1-3 sentences, then at most \
five key points.
- Every key point must list the `id`s of the passages that support it in `sources`. A key point \
without sources will be deleted.
- When the question is about what the City said or did, include `city_said`: Management Comment, \
Action Plans and Reported Status, each point attributed to Management ("Management said ...", \
"Management reported ...") and each with its `sources`. Leave it out when there is nothing to \
report.
- To show a timeline with your answer, list it in `timelines` (at most three); the page displays \
it in full, so key points should summarise it, not repeat it.

Wording
- An Audit Observation is a deficiency, non-compliance or weakness COA found. It is NOT a finding \
of fraud, corruption or wrongdoing. Never use words such as "fraud", "corruption", "stole", \
"illegal" or "misused" unless the passage itself uses them, and never describe a matter more \
strongly than the report does.
- Say "COA observed" or "COA recommended", not "COA found the City guilty". Refer to the audited \
agency as "the City of Manila".
- Management's response is Management Comment; COA's reply is the Auditor's Rejoinder. If a \
passage records one, present it fairly and attribute it to Management.
- A Status of Implementation is COA's assessment and the authoritative one. What Management says \
it did (the "Management action" in Part III) is Management's own account: attribute it \
("Management said ..."), and never present it as COA's finding or as proof the recommendation was \
implemented.
- Management's Reported Status (the AAPSI's status column, repeated in the APMT) is a claim by \
Management. Never merge it with COA's Status of Implementation: give them separately, each \
attributed. When a `validation` has a `disagreement`, point it out in your answer, e.g. \
"Management reported this as implemented; COA assessed it as partially implemented". Management's \
"Ongoing" has no COA equivalent: do not call it a disagreement.
"""

SEARCH_TOOL = ToolSpec(
    name="search",
    description=(
        "Search COA's Annual Audit Reports on the City of Manila, by exact words or by meaning: "
        "Part II Audit Observations, Part III follow-up of Prior Years' Recommendations, and the "
        "2023-2024 AAPSI (Management's Action Plans) and APMT (COA's validation of them). "
        "Returns passages, each with an `id`, its `citation` and the observation it is about "
        "(`origin_year`, `origin_observation`, for the `timeline` tool); with no `years` filter "
        "they are ordered newest year first."
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
            "parts": {
                "type": "array",
                "items": {"type": "string", "enum": ["II", "III", "AAPSI", "APMT"]},
                "description": (
                    "Restrict to Part II (observations), Part III (follow-up), the AAPSI "
                    "(Management's Action Plans) and/or the APMT (COA's validation)."
                ),
            },
            "observation": {
                "type": "integer",
                "description": "Restrict to this Part II Audit Observation number.",
            },
            "status": {
                "type": "string",
                "enum": ["Implemented", "Partially Implemented", "Not Implemented"],
                "description": (
                    "Restrict Part III and APMT results to this COA Status of Implementation."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"How many Audit Observations (or Part III blocks) to return: default "
                    f"{DEFAULT_LIMIT}, at most {MAX_SEARCH_RESULTS}."
                ),
            },
        },
        "required": ["query"],
    },
)

TIMELINE_TOOL = ToolSpec(
    name="timeline",
    description=(
        "How one Audit Observation's Recommendations were followed up: when it was raised "
        "(Part II, if in the 2020-2024 AARs) and COA's Status of Implementation in each later "
        "AAR's Part III, with Management's action and reason, plus Management's Action Plan "
        "and Reported Status (AAPSI) and COA's validation (APMT) where there are any, with any "
        "disagreement between the two statuses. Works for observations raised before 2020."
    ),
    parameters={
        "type": "object",
        "properties": {
            "origin_year": {
                "type": "integer",
                "description": "The AAR year the observation was first raised in.",
            },
            "origin_observation": {
                "type": "integer",
                "description": "The observation number in that AAR.",
            },
        },
        "required": ["origin_year", "origin_observation"],
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
            "city_said": {
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
                "description": (
                    "What the City said: Management Comment, Action Plan or Reported Status, "
                    "attributed to Management."
                ),
            },
            "timelines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "origin_year": {"type": "integer"},
                        "origin_observation": {"type": "integer"},
                    },
                    "required": ["origin_year", "origin_observation"],
                },
                "description": "Timelines fetched with the timeline tool to display (at most 3).",
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
    city_said: list[KeyPoint] = Field(default_factory=list, max_length=MAX_CITY_SAID)
    timelines: list[Timeline] = Field(default_factory=list, max_length=MAX_TIMELINES)


class NotCovered(BaseModel):
    type: Literal["not_covered"] = "not_covered"
    message: str


class Status(BaseModel):
    type: Literal["status"] = "status"
    message: str


Event = Status | Answer | NotCovered


class AnswerEngine:
    def __init__(self, adapter: ModelAdapter, index: Index, max_search_rounds: int = 6):
        self._adapter = adapter
        self._index = index
        self._max_search_rounds = max_search_rounds

    def ask(self, question: str) -> Iterator[Event]:
        """Yield `Status` updates while working, then exactly one `Answer` or `NotCovered`."""
        messages = [Message(role="user", text=question)]
        seen: dict[str, Piece] = {}
        timelines: dict[tuple[int, int], Timeline] = {}
        nudged = False
        for round_number in range(self._max_search_rounds + 1):
            last_round = round_number == self._max_search_rounds
            tools = [SUBMIT_TOOL] if last_round else [SEARCH_TOOL, TIMELINE_TOOL, SUBMIT_TOOL]
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
                    yield finalise(call.args, seen, timelines)
                    return
                if call.name in ARGUMENT_ERRORS and not last_round:
                    yield Status(message=status_message(call))
                    try:
                        content = (
                            self._run_search(call, seen)
                            if call.name == "search"
                            else self._run_timeline(call, seen, timelines)
                        )
                    except (TypeError, ValueError, KeyError, OverflowError):
                        # Tell the model what was wrong so it can retry, instead of failing.
                        content = {"error": ARGUMENT_ERRORS[call.name]}
                    results.append(ToolResult(call, content))
                else:
                    results.append(ToolResult(call, {"error": f"unknown tool {call.name}"}))
            messages.append(Message(role="tool", tool_results=results))
        yield NotCovered(message=NOT_COVERED_DEFAULT)

    def _run_search(self, call: ToolCall, seen: dict[str, Piece]) -> list[dict]:
        args = call.args
        observation = args.get("observation")
        hits = self._index.search(
            str(args.get("query", "")),
            years=[int(year) for year in args.get("years") or []] or None,
            parts=as_list(args.get("parts")) or None,
            observation=int(observation) if observation is not None else None,
            status=str(args["status"]) if args.get("status") else None,
            limit=max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_SEARCH_RESULTS)),
        )
        passages = []
        for whole in self._index.expand(hits):
            for piece in whole.pieces:
                seen[piece.key] = piece
                passages.append(
                    {
                        "id": piece.key,
                        "citation": piece.citation,
                        "title": piece.title,
                        "kind": piece.kind,
                        "origin_year": piece.origin_year,
                        "origin_observation": piece.origin_observation,
                        "matched": piece.key in whole.matched,
                        "text": piece.text[:MAX_PIECE_CHARS_TO_MODEL],
                    }
                )
        return passages

    def _run_timeline(
        self, call: ToolCall, seen: dict[str, Piece], timelines: dict[tuple[int, int], Timeline]
    ) -> dict:
        year, observation = int(call.args["origin_year"]), int(call.args["origin_observation"])
        timeline = self._index.timeline(year, observation)
        if timeline is None:
            return {"error": f"the reports have nothing on CY {year} Observation No. {observation}"}
        timelines[(year, observation)] = timeline
        for key in timeline.keys:  # the model may cite any step it was shown
            piece = self._index.piece(key)
            if piece:
                seen[key] = piece
        return {"timeline": timeline.model_dump(mode="json")}


def as_list(value) -> list[str]:
    """A list of strings from a model argument that may be a bare string or missing."""
    return [str(item) for item in ([value] if isinstance(value, str) else value or [])]


ARGUMENT_ERRORS = {
    "search": (
        "years must be a list of integers, parts a list of strings, observation and limit "
        "integers, status one of the three Status of Implementation values"
    ),
    "timeline": "origin_year and origin_observation must be integers",
}


def status_message(call: ToolCall) -> str:
    if call.name == "timeline":
        args = call.args
        return (
            f"Following CY {args.get('origin_year')} Observation No."
            f" {args.get('origin_observation')} through later reports"
        )
    return f"Searching the reports for “{call.args.get('query', '')}”"


def finalise(
    args: dict, seen: dict[str, Piece], timelines: dict[tuple[int, int], Timeline]
) -> Answer | NotCovered:
    """Validate the model's submitted answer against what it retrieved."""
    if args.get("covered") is not True:
        message = clip(str(args.get("not_covered_message") or ""), MAX_NOT_COVERED_CHARS)
        return NotCovered(message=message or NOT_COVERED_DEFAULT)
    key_points = cited_points(args.get("key_points"), seen)
    if not key_points:
        return NotCovered(message=NOT_COVERED_DEFAULT)
    summary = clip(str(args.get("summary") or ""), MAX_SUMMARY_CHARS)
    return Answer(
        summary=summary,
        key_points=key_points[:MAX_KEY_POINTS],
        city_said=cited_points(args.get("city_said"), seen)[:MAX_CITY_SAID],
        timelines=chosen_timelines(args.get("timelines"), timelines),
    )


def cited_points(raw_points: object, seen: dict[str, Piece]) -> list[KeyPoint]:
    """The points whose `sources` name pieces the model retrieved; the rest are dropped."""
    points = []
    for raw in raw_points if isinstance(raw_points, list) else []:
        if not isinstance(raw, dict):
            continue
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
            points.append(KeyPoint(text=text, citations=list(citations.values())))
    return points


def chosen_timelines(
    requested: object, retrieved: dict[tuple[int, int], Timeline]
) -> list[Timeline]:
    """The timelines the model asked to show, only ever ones the `timeline` tool returned."""
    chosen: dict[tuple[int, int], Timeline] = {}
    for item in requested if isinstance(requested, list) else []:
        try:
            key = (int(item["origin_year"]), int(item["origin_observation"]))
        except (TypeError, ValueError, KeyError):
            continue
        if key in retrieved:
            chosen[key] = retrieved[key]
    return list(chosen.values())[:MAX_TIMELINES]


def clip(text: str, limit: int) -> str:
    """Trim to `limit` characters at a word boundary, marking the cut."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
