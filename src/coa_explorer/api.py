"""The web app: one FastAPI service that streams answers and serves the React page."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from coa_explorer.answer import AnswerEngine

WEB_DIR = Path(__file__).parent / "web"
MAX_QUESTION_CHARS = 1000

log = logging.getLogger(__name__)


class AskRequest(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str = Field(default="Something went wrong answering that. Please try again.")


def create_app(engine: AnswerEngine) -> FastAPI:
    app = FastAPI(title="COA Audit Explorer")

    @app.post("/api/ask")
    def ask(request: AskRequest) -> StreamingResponse:
        """Stream newline-delimited JSON events: `status` updates, then one `answer`,
        `not_covered` or `error` event."""
        return StreamingResponse(
            ndjson(engine, request.question), media_type="application/x-ndjson"
        )

    @app.get("/")
    def page() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app


def ndjson(engine: AnswerEngine, question: str) -> Iterator[str]:
    try:
        for event in engine.ask(question):
            yield event.model_dump_json() + "\n"
    except Exception:
        # The details stay in the server log; the visitor gets a generic message.
        log.exception("answering failed")
        yield ErrorEvent().model_dump_json() + "\n"
