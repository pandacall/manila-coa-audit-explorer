"""The web app: one FastAPI service that streams answers and serves the React page."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from coa_explorer.answer import (
    EXAMPLE_QUESTIONS,
    MAX_HISTORY_EXCHANGES,
    Answer,
    AnswerEngine,
    Exchange,
    Question,
    Status,
)
from coa_explorer.demo import DEMO_LIMIT_MESSAGE, Demo, Outcome, Rating, SavedAnswer
from coa_explorer.models import Usage

WEB_DIR = Path(__file__).parent / "web"
NDJSON = "application/x-ndjson"

log = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: Question
    # The last few exchanges of the conversation, oldest first. The browser keeps them; the
    # server only passes them to the model and never stores them.
    history: list[Exchange] = Field(default_factory=list, max_length=MAX_HISTORY_EXCHANGES)


class FeedbackRequest(BaseModel):
    question_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    rating: Rating


class Examples(BaseModel):
    questions: list[str]


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str = Field(default="Something went wrong answering that. Please try again.")


class RateLimitedEvent(BaseModel):
    type: Literal["rate_limited"] = "rate_limited"
    message: str


class DemoLimitEvent(BaseModel):
    type: Literal["demo_limit"] = "demo_limit"
    message: str = DEMO_LIMIT_MESSAGE
    examples: list[SavedAnswer] = Field(default_factory=list)


def create_app(engine: AnswerEngine, demo: Demo | None = None) -> FastAPI:
    """`demo` adds the public-demo limits, question log and feedback; without it (local
    development) there are no limits and nothing is logged."""
    app = FastAPI(title="COA Audit Explorer")

    @app.post("/api/ask")
    def ask(request: AskRequest, http: Request) -> Response:
        """Stream newline-delimited JSON events: `status` updates, then one `answer`,
        `not_covered` or `error` event. Over a limit, one `rate_limited` or `demo_limit` event
        with status 429 instead."""
        if demo:
            try:
                verdict = demo.admit(client_ip(http))
            except Exception:
                # Fail closed: without the counters there is no protection against a surprise bill.
                log.exception("could not check the demo limits")
                return line_response(ErrorEvent(), 503)
            if verdict == "rate_limited":
                return line_response(RateLimitedEvent(message=demo.rate_limited_message()), 429)
            if verdict == "capped":
                return line_response(DemoLimitEvent(examples=demo.examples), 429)
        return StreamingResponse(
            ndjson(engine, request.question, request.history, demo), media_type=NDJSON
        )

    @app.post("/api/feedback", status_code=204)
    def feedback(request: FeedbackRequest) -> None:
        """Store a 👍/👎 against the logged question it is about."""
        try:
            found = bool(demo) and demo.rate(request.question_id, request.rating)
        except Exception:
            log.exception("could not store feedback")
            raise HTTPException(503, "Could not save your feedback.") from None
        if not found:
            raise HTTPException(404, "No such question.")

    @app.get("/api/examples")
    def examples() -> Examples:
        """Example questions the reports can answer, for the page to offer."""
        return Examples(questions=list(EXAMPLE_QUESTIONS))

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def client_ip(request: Request) -> str:
    """The visitor's address. Cloud Run appends it as the last X-Forwarded-For entry; earlier
    entries are whatever the client claimed, so they are ignored."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def line_response(event: BaseModel, status_code: int) -> Response:
    return Response(event.model_dump_json() + "\n", status_code, media_type=NDJSON)


def ndjson(
    engine: AnswerEngine, question: str, history: list[Exchange], demo: Demo | None
) -> Iterator[str]:
    started = time.monotonic()
    usage = Usage()
    final: BaseModel | None = None
    try:
        for event in engine.ask(question, usage, history=history):
            if isinstance(event, Status):
                yield event.model_dump_json() + "\n"
            else:
                final = event
    except Exception:
        # The details stay in the server log; the visitor gets a generic message.
        log.exception("answering failed")
    final = final or ErrorEvent()
    data = final.model_dump(mode="json")
    if demo:
        question_id = demo.log_question(
            question,
            outcome_of(final),
            citations_of(final),
            round((time.monotonic() - started) * 1000),
            usage,
        )
        if question_id:
            data["question_id"] = question_id  # logged before the answer, so feedback can follow
    yield json.dumps(data, ensure_ascii=False) + "\n"


def outcome_of(final: BaseModel) -> Outcome:
    if isinstance(final, Answer):
        return "answer"
    return "error" if isinstance(final, ErrorEvent) else "not_covered"


def citations_of(final: BaseModel) -> list[str]:
    if not isinstance(final, Answer):
        return []
    texts = [c.text for point in final.key_points for c in point.citations]
    return list(dict.fromkeys(texts))
