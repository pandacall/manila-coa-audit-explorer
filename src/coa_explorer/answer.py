"""The answer engine: a tool-using loop that turns a question into a cited Answer.

The model may call `search`, `timeline`, `financial_lookup` and `financial_change` over the index,
then must finish with `submit_answer`.
An answer can carry "What the City said" (Management Comment or Reported Status), cited like key
points and shown apart from them. The model cites by piece id; the Citation text comes from the
index, never from the model, and a key point may only cite pieces (or financial figures) the model
actually retrieved. Figures and the differences between years come from `financial_lookup`; the
model never does arithmetic (`financial_change` works out a difference for two lines COA labelled
differently in two years). Key
points left without a Citation are removed, and an answer left with none is reported as not
covered. A timeline shown with an answer is the one the `timeline` tool returned, not anything the
model wrote.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from coa_explorer.financial import FUNDS, STATEMENT_NAMES
from coa_explorer.financial_lookup import FinancialChange, FinancialLookup
from coa_explorer.models import Message, ModelAdapter, ToolCall, ToolResult, ToolSpec, Usage
from coa_explorer.search import DEFAULT_LIMIT, Index, Piece
from coa_explorer.timeline import Timeline

MAX_SUMMARY_CHARS = 600
MAX_KEY_POINTS = 6
MAX_CITY_SAID = 4
MAX_TIMELINES = 3
MAX_SEARCH_RESULTS = 25
MAX_KEY_POINT_CHARS = 500
MAX_NOT_COVERED_CHARS = 600  # room for an explanation of what the app covers, in Filipino
MAX_SUGGESTIONS = 3
MAX_SUGGESTION_CHARS = 200
MAX_PIECE_CHARS_TO_MODEL = 2500
MAX_QUESTION_CHARS = 1000
MAX_HISTORY_EXCHANGES = 3
MAX_HISTORY_ANSWER_CHARS = 3000
NOT_COVERED_DEFAULT = (
    "The Annual Audit Reports I have don't cover that, or I couldn't ground an answer in them."
)
OUT_OF_SCOPE_DEFAULT = (
    "I can only answer questions about COA's Annual Audit Reports on the City of Manila, "
    "2020–2024: the Audit Observations and Recommendations, whether the City acted on them, and "
    "the City's financial statements."
)
# Questions the reports can answer: shown on the page, suggested when a question is not covered
# and the model offers none, and answered ahead of time (`coa-explorer save-examples`) to show when
# the demo's daily cap is reached.
EXAMPLE_QUESTIONS = (
    "What did COA observe about cash advances in Manila?",
    "Did Manila comply with IPSAS 1 in its financial statements? Which years?",
    "Did Manila act on COA's recommendations about cash advances?",
)

SYSTEM_PROMPT = """\
You answer questions about the Commission on Audit's (COA) Annual Audit Reports (AARs) on the \
City of Manila, 2020-2024, for ordinary residents, journalists and students. Part II holds each \
year's Audit Observations and Recommendations. Part III holds, for each AAR, COA's Status of \
Implementation of Prior Years' Recommendations (Implemented, Partially Implemented or Not \
Implemented), with Management's action and the reason given for partial or non-implementation. \
The Executive Summary (search it with `parts` ["ES"]) is COA's own overview of the year: the \
City's financial and operational highlights, the scope of the audit, a summary of the audit \
opinion and significant observations, and the status of prior years' recommendations. The \
Auditor's Report (Part I; search it with `parts` ["I"]) is COA's formal opinion on whether the \
Financial Statements are fairly presented. Two short documents open each AAR: the transmittal \
letter (part "TL"), in which COA sends the AAR to the Mayor, restating the opinion and, for most \
years, the significant observations; and the Management Responsibility statement (part "MR"), in \
which the City's own officials state that Management is responsible for the Financial Statements \
and for the internal controls behind them. The statement is Management's, not COA's: attribute \
it. The Financial Statements (Part I) and the Annexes (Part IV, the same statements broken down \
by Fund) hold the City's figures, and only `financial_lookup` reads them. The Notes to Financial \
Statements (part "NOTES") \
explain what lies behind those figures: the accounting policies, then a Note for each kind of \
account with a table of its amounts and the reasons for the changes. Amounts in the Notes are in \
Philippine pesos unless a Note says otherwise.
For 2023 and 2024 there are two more documents: the AAPSI (part "AAPSI") is Management's own \
report of its Action Plan for each Recommendation, with the person or department responsible, \
target dates and the Reported Status Management claims; the APMT (part "APMT") is COA's \
validation of it, with COA's own Status of Implementation.

How to work
- The question may follow earlier exchanges of the same conversation, which come before it. Use \
them only to work out what a follow-up such as "What about 2022?" or "Did they fix it?" refers to \
(the topic, the year, the observation), then search again: an earlier answer is not a source, and \
you may cite only passages and figures returned for this question.
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
- For a year's highlights, `search` with an empty query, `parts` ["ES"] and that `years` filter: \
you get the Executive Summary's sections in reading order, each with its own citation. For COA's \
opinion on the Financial Statements, `search` `parts` ["I"] with the `years` filter: the \
"Qualified Opinion" (or other opinion) section states the opinion, and the section on its bases \
gives the matters behind it.
- To explain a figure or account, `search` `parts` ["NOTES"] with the year: each hit is a passage \
of one Note, cited by Note and page, and a Note's tables arrive as markdown. To read a Note by \
its number, search with an empty query, `parts` ["NOTES"], `years` and `observation` set to the \
Note number. A Note's amounts are exactly as COA printed them: quote them as written and never \
add, subtract or compare them yourself.
- To find out whether Manila acted on a recommendation, find the observation with `search`, then \
call `timeline` with the `origin_year` and `origin_observation` printed on its results. It returns \
when the observation was raised and COA's Status of Implementation in each later AAR, each step \
with its own `id` and citation. Observations raised before 2020 have a timeline too, cited to the \
AAR that tracks them. A step can also hold the AAPSI's `action_plans` (Management's account) and \
the APMT's `validations` (COA's Status of Implementation). To review one year's backlog, `search` \
with `parts` ["III"], that `years` filter and a `status`, and raise `limit`.
- For any question about an amount (cash, receipts, spending, assets, liabilities, net assets, \
budget against actual, a change between years, a breakdown by Fund), call `financial_lookup`, not \
`search`. Give it the line item in COA's words (such as "Cash and Cash Equivalents") and the \
`years`; a year's figure is the one in that year's AAR. It returns exact amounts in Philippine \
pesos, each figure with its `id` and citation, and `changes` between the years you asked for, \
worked out by the tool. Never calculate, add, subtract, round, convert or estimate a figure \
yourself: quote `display` (and `display_change`, `display_percent`) as given, so the amount \
carries the peso sign and its unit, and cite the `id` of each figure you use (a change cites both \
of its `ids`). Part I statements are for the City as a whole ("All Funds"); the Annexes give the \
General Fund, the Special Education Fund and the Trust Fund: name the Fund each amount is for. The \
budget statement (SCBAA) has Original budget, Final budget and Actual, and COA's "Difference \
final budget and actual" (Final minus Actual: a positive difference means the actual amount fell \
short of the budget). Annex labels differ from year to year (a Fund's cash may be "Total Cash" \
in one year and "Total Cash and Cash Equivalents" in another): if you need a Fund breakdown and \
only "All Funds" came back, look up again with other words. When you find the same line under \
two labels in two years, pass the two figures' `id`s to `financial_change` and use what it \
returns; never subtract them yourself. If no figure comes back, the reports have no such line: \
say so.
- Answer ONLY from passages `search` and `timeline` returned, and figures `financial_lookup` \
returned. Never use outside knowledge, never \
guess, never calculate or infer figures that the passages do not state. If the passages do not \
address the question, submit with covered=false, say so plainly, and give up to three \
`suggested_questions` on related matters the reports do cover, going by what your searches \
returned.
- Questions about anything else are out of scope: other cities or agencies, news, politics, \
elections, or judgements of people. Do not search for them: submit at once with covered=false \
and out_of_scope=true, and in `not_covered_message` explain in a sentence or two that you answer \
only from COA's 2020-2024 Annual Audit Reports on the City of Manila (its Audit Observations and \
Recommendations, whether the City acted on them, and its financial statements). Give \
`suggested_questions` too.
- Answer in the language of the question: English, Filipino or Taglish (a mix of the two), \
whichever the visitor used. The reports are in English, so always search in English, in COA's \
words. Where COA's exact words matter (an opinion, a status, a term, a figure's line item), quote \
the AAR's English in quotation marks rather than translating it.
- Write in plain language. Keep it short: a summary of 1-3 sentences, then at most \
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
- COA's opinion on the Financial Statements is unmodified (also called unqualified, or clean), \
qualified, adverse, or a disclaimer. A qualified opinion means COA found the statements fairly \
presented except for the matters it describes. Say which opinion COA gave in the words of the \
Auditor's Report, and never call a qualified opinion clean.
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
        "Part II Audit Observations, Part III follow-up of Prior Years' Recommendations, the "
        "Executive Summary, the Auditor's Report, the transmittal letter, the Management "
        "Responsibility statement, the Notes to Financial Statements, and the 2023-2024 "
        "AAPSI (Management's Action Plans) and APMT (COA's validation of them). "
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
                "items": {
                    "type": "string",
                    "enum": ["ES", "I", "TL", "MR", "NOTES", "II", "III", "AAPSI", "APMT"],
                },
                "description": (
                    "Restrict to the Executive Summary (ES), the Auditor's Report (I), the "
                    "transmittal letter (TL), the Management Responsibility statement (MR), "
                    "the Notes to Financial Statements (NOTES), Part II (observations), "
                    "Part III (follow-up), the AAPSI (Management's Action Plans) and/or the "
                    "APMT (COA's validation)."
                ),
            },
            "observation": {
                "type": "integer",
                "description": (
                    "Restrict to this Part II Audit Observation number, or with parts [NOTES] "
                    "this Note number."
                ),
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

FINANCIAL_LOOKUP_TOOL = ToolSpec(
    name="financial_lookup",
    description=(
        "Exact peso amounts from the Financial Statements (Part I) and Annexes (Part IV) of the "
        "2020-2024 AARs, found by the words of the line item. Each figure has an `id`, its "
        "`citation` (statement and line item), its Fund and its amounts by column (the budget "
        "statement has Original budget, Final budget, Actual and the difference columns). When "
        "the line item is found in several of the `years`, `changes` gives the exact difference "
        "and percentage from each year to the next, computed here. Amounts are in Philippine "
        "pesos, exact to the centavo."
    ),
    parameters={
        "type": "object",
        "properties": {
            "line_item": {
                "type": "string",
                "description": "The line item in COA's words, e.g. 'Cash and Cash Equivalents'.",
            },
            "years": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "AAR years (2020-2024); each gives that year's own figure.",
            },
            "statement": {
                "type": "string",
                "enum": list(STATEMENT_NAMES),
                "description": (
                    "Restrict to one statement: SFPo (Financial Position), SFPe (Financial "
                    "Performance), SCNAE (Changes in Net Assets/Equity), SCF (Cash Flows) or "
                    "SCBAA (Comparison of Budget and Actual Amounts)."
                ),
            },
            "fund": {
                "type": "string",
                "enum": list(FUNDS),
                "description": (
                    "Restrict to one Fund. 'All Funds' is the City as a whole (Part I, and each "
                    "Annex's Total column). Leave out to get both, with the Fund breakdown."
                ),
            },
        },
        "required": ["line_item", "years"],
    },
)

FINANCIAL_CHANGE_TOOL = ToolSpec(
    name="financial_change",
    description=(
        "The exact change between two lines `financial_lookup` returned, for when COA labelled "
        "the same line differently in two years so that `changes` could not pair them. Both "
        "must be for the same Fund and statement and from different years, and you vouch that "
        "they are the same item. Returns the difference and percentage for each amount column "
        "they share, computed here."
    ),
    parameters={
        "type": "object",
        "properties": {
            "from_id": {"type": "string", "description": "The `id` of one figure."},
            "to_id": {"type": "string", "description": "The `id` of the other figure."},
            "column": {
                "type": "string",
                "description": "Only this column, e.g. 'Actual'; default every shared amount.",
            },
        },
        "required": ["from_id", "to_id"],
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
            "out_of_scope": {
                "type": "boolean",
                "description": (
                    "True if the question is not about COA's 2020-2024 AARs on the City of "
                    "Manila (other cities, news, politics, people)."
                ),
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
            "suggested_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "When covered is false: up to three related questions the AARs can answer, "
                    "in the language of the question."
                ),
            },
        },
        "required": ["covered"],
    },
)


@dataclass(frozen=True)
class Source:
    """What a key point may cite: a piece or a financial figure the model was shown."""

    citation: str
    title: str


class Citation(BaseModel):
    text: str = Field(
        description="COA's format, e.g. 'CY 2023 AAR, Part II, Observation No. 5, p. 71' or "
        "'CY 2023 AAR, Executive Summary, Section E, p. iii' or "
        "'CY 2023 AAR, Part I, Notes to Financial Statements, Note 4, p. 30'"
    )
    title: str = Field(
        description="Title of the Audit Observation, of the Executive Summary or Auditor's "
        "Report section, or of the Note"
    )


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
    """No answer: the reports don't cover the question (`not_found`), or it is about something
    else altogether and was refused (`out_of_scope`)."""

    type: Literal["not_covered"] = "not_covered"
    reason: Literal["not_found", "out_of_scope"] = "not_found"
    message: str
    suggestions: list[str] = Field(
        default_factory=lambda: list(EXAMPLE_QUESTIONS), max_length=MAX_SUGGESTIONS
    )


class Status(BaseModel):
    type: Literal["status"] = "status"
    message: str


Event = Status | Answer | NotCovered


class Exchange(BaseModel):
    """One earlier question and the answer the visitor was shown, as the browser sends it back.

    It is context for a follow-up question only: nothing in it can be cited."""

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]
    answer: Annotated[str, StringConstraints(max_length=MAX_HISTORY_ANSWER_CHARS)] = ""


class AnswerEngine:
    def __init__(self, adapter: ModelAdapter, index: Index, max_search_rounds: int = 6):
        self._adapter = adapter
        self._index = index
        self._max_search_rounds = max_search_rounds

    def ask(
        self,
        question: str,
        usage: Usage | None = None,
        retrieved: dict[str, Piece] | None = None,
        history: Sequence[Exchange] = (),
    ) -> Iterator[Event]:
        """Yield `Status` updates while working, then exactly one `Answer` or `NotCovered`.

        The tokens the model reports using are added to `usage`, if given. Pass a dict as
        `retrieved` to learn which pieces (by id) the model was shown. `history` holds the
        earlier exchanges of the conversation, oldest first; the model reads them to make sense
        of a follow-up, but cites only what it retrieves for this question.
        """
        messages = []
        for exchange in history[-MAX_HISTORY_EXCHANGES:]:
            messages.append(Message(role="user", text=exchange.question))
            messages.append(Message(role="model", text=exchange.answer or "(no answer)"))
        messages.append(Message(role="user", text=question))
        seen = retrieved if retrieved is not None else {}
        figures: dict[str, Source] = {}  # financial figures the model was shown, by id
        timelines: dict[tuple[int, int], Timeline] = {}
        nudged = False
        for round_number in range(self._max_search_rounds + 1):
            last_round = round_number == self._max_search_rounds
            tools = (
                [SUBMIT_TOOL]
                if last_round
                else [
                    SEARCH_TOOL,
                    TIMELINE_TOOL,
                    FINANCIAL_LOOKUP_TOOL,
                    FINANCIAL_CHANGE_TOOL,
                    SUBMIT_TOOL,
                ]
            )
            turn = self._adapter.generate(SYSTEM_PROMPT, messages, tools)
            if usage is not None and turn.usage is not None:
                usage.add(turn.usage)
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
                    yield finalise(call.args, {**seen, **figures}, timelines)
                    return
                if call.name in ARGUMENT_ERRORS and not last_round:
                    yield Status(message=status_message(call))
                    try:
                        content = self._run_tool(call, seen, figures, timelines)
                    except (TypeError, ValueError, KeyError, OverflowError) as error:
                        # Tell the model what was wrong so it can retry, instead of failing.
                        content = {"error": ARGUMENT_ERRORS[call.name]}
                        if isinstance(error, ToolError):
                            content["error"] = str(error)
                    results.append(ToolResult(call, content))
                else:
                    results.append(ToolResult(call, {"error": f"unknown tool {call.name}"}))
            messages.append(Message(role="tool", tool_results=results))
        yield NotCovered(message=NOT_COVERED_DEFAULT)

    def _run_tool(
        self,
        call: ToolCall,
        seen: dict[str, Piece],
        figures: dict[str, Source],
        timelines: dict[tuple[int, int], Timeline],
    ) -> list[dict] | dict:
        if call.name == "search":
            return self._run_search(call, seen)
        if call.name == "financial_lookup":
            return self._run_financial_lookup(call, figures)
        if call.name == "financial_change":
            return self._run_financial_change(call, figures)
        return self._run_timeline(call, seen, timelines)

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

    def _run_financial_lookup(self, call: ToolCall, figures: dict[str, Source]) -> dict:
        args = call.args
        years = args["years"]
        if not isinstance(years, list):
            raise TypeError("years must be a list")
        fund = args.get("fund")
        if fund is not None and fund not in FUNDS:
            raise ToolError(f"unknown fund {fund!r}; use one of {', '.join(FUNDS)}")
        statement = args.get("statement")
        if statement is not None and statement not in STATEMENT_NAMES:
            raise ToolError(
                f"unknown statement {statement!r}; use one of {', '.join(STATEMENT_NAMES)}"
            )
        result = self._index.financial_lookup(
            str(args["line_item"]),
            years=[int(year) for year in years],
            statement=statement,
            fund=fund,
        )
        for figure in result.figures:
            figures[figure.key] = Source(
                figure.citation, f"{figure.line_item} ({STATEMENT_NAMES[figure.statement]})"
            )
        return financial_content(result)

    def _run_financial_change(self, call: ToolCall, figures: dict[str, Source]) -> dict:
        from_id, to_id = str(call.args["from_id"]), str(call.args["to_id"])
        for key in (from_id, to_id):
            if key not in figures:
                raise ToolError(f"{key} was not returned by financial_lookup; look it up first")
        try:
            changes = self._index.financial_change(from_id, to_id, call.args.get("column"))
        except ValueError as error:
            raise ToolError(str(error)) from error
        return {"units": FIGURES_UNITS, "changes": [change_content(c) for c in changes]}

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


FIGURES_UNITS = (
    "Philippine pesos (₱), exact to the centavo. Quote `display` as given; never calculate."
)


def financial_content(result: FinancialLookup) -> dict:
    """What the model is shown of a lookup: amounts as exact decimal strings, and in pesos."""
    return {
        "units": FIGURES_UNITS,
        "figures": [
            {
                "id": figure.key,
                "citation": figure.citation,
                "year": figure.aar_year,
                "statement": figure.statement,
                "printed_in": figure.source,
                "fund": figure.fund,
                "section": figure.section,
                "line_item": figure.line_item,
                "amounts": {column: str(amount) for column, amount in figure.amounts.items()},
                "display": figure.display,
            }
            for figure in result.figures
        ],
        "changes": [change_content(change) for change in result.changes],
    }


def change_content(change: FinancialChange) -> dict:
    return {
        "statement": change.statement,
        "fund": change.fund,
        "section": change.section,
        "line_item": change.line_item,
        "column": change.column,
        "from_year": change.from_year,
        "to_year": change.to_year,
        "from": str(change.from_amount),
        "to": str(change.to_amount),
        "change": str(change.change),
        "percent": None if change.percent is None else str(change.percent),
        "display_change": change.display_change,
        "display_percent": change.display_percent,
        "ids": list(change.keys),
    }


def as_list(value) -> list[str]:
    """A list of strings from a model argument that may be a bare string or missing."""
    return [str(item) for item in ([value] if isinstance(value, str) else value or [])]


ARGUMENT_ERRORS = {
    "search": (
        "years must be a list of integers, parts a list of strings, observation and limit "
        "integers, status one of the three Status of Implementation values"
    ),
    "timeline": "origin_year and origin_observation must be integers",
    "financial_lookup": (
        "line_item must be a string, years a list of integers, statement one of SFPo, SFPe, "
        "SCNAE, SCF, SCBAA, fund one of the listed Funds"
    ),
    "financial_change": "from_id and to_id must be ids of figures financial_lookup returned",
}


class ToolError(ValueError):
    """A tool call the engine can explain to the model, so that it can correct itself."""


def status_message(call: ToolCall) -> str:
    if call.name == "financial_change":
        years = [str(call.args.get(key, "")).split("-")[0] for key in ("from_id", "to_id")]
        return f"Working out the change between CY {years[0]} and CY {years[1]}"
    if call.name == "financial_lookup":
        return f"Looking up “{call.args.get('line_item', '')}” in the financial statements"
    if call.name == "timeline":
        args = call.args
        return (
            f"Following CY {args.get('origin_year')} Observation No."
            f" {args.get('origin_observation')} through later reports"
        )
    return f"Searching the reports for “{call.args.get('query', '')}”"


def finalise(
    args: dict, seen: Mapping[str, Piece | Source], timelines: dict[tuple[int, int], Timeline]
) -> Answer | NotCovered:
    """Validate the model's submitted answer against what it retrieved."""
    if args.get("covered") is not True:
        message = clip(str(args.get("not_covered_message") or ""), MAX_NOT_COVERED_CHARS)
        suggestions = suggested_questions(args.get("suggested_questions")) or list(
            EXAMPLE_QUESTIONS
        )
        if args.get("out_of_scope") is True:
            return NotCovered(
                reason="out_of_scope",
                message=message or OUT_OF_SCOPE_DEFAULT,
                suggestions=suggestions,
            )
        return NotCovered(message=message or NOT_COVERED_DEFAULT, suggestions=suggestions)
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


def suggested_questions(raw: object) -> list[str]:
    """The model's suggested questions: non-empty, short, at most a few."""
    questions = [clip(item, MAX_SUGGESTION_CHARS) for item in as_list(raw)]
    return [question for question in questions if question][:MAX_SUGGESTIONS]


def cited_points(raw_points: object, seen: Mapping[str, Piece | Source]) -> list[KeyPoint]:
    """The points whose `sources` name pieces the model retrieved; the rest are dropped."""
    points = []
    for raw in raw_points if isinstance(raw_points, list) else []:
        if not isinstance(raw, dict):
            continue
        citations: dict[str, Citation] = {}
        sources = raw.get("sources") or []
        for source in [sources] if isinstance(sources, str) else sources:
            cited = seen.get(source)
            if cited:
                citations.setdefault(
                    cited.citation, Citation(text=cited.citation, title=cited.title)
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
