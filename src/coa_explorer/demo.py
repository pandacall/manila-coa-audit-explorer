"""Guard rails for the public demo: rate limits, a daily cap, an anonymous question log, feedback.

All mutable state sits behind the narrow `Store` seam (Firestore in production, so the counts are
right across instances and restarts; a fake in tests). Three rules shape this module:

- The visitor's IP is only ever used to key a counter, as a salted hash; it is never stored with a
  logged question, and the logged question carries no user identifier of any kind.
- If the store cannot be reached the demo fails closed (`admit` raises), because the point of the
  limits is to stop a surprise bill. Logging is the opposite: a failed log write never costs the
  visitor their answer.
- Questions turned away by a limit never reach the model and are not logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel

from coa_explorer.answer import Answer
from coa_explorer.models import Usage

DEFAULT_HOURLY_LIMIT = 10
DEFAULT_DAILY_CAP = 300
LOG_RETENTION = timedelta(days=30)
DEMO_LIMIT_MESSAGE = "Demo limit reached for today"

Rating = Literal["up", "down"]
Admission = Literal["ok", "rate_limited", "capped"]
Outcome = Literal["answer", "not_covered", "error"]

log = logging.getLogger(__name__)


class Store(Protocol):
    def take(self, counter: str, limit: int, expire_at: datetime) -> bool:
        """Atomically add one to the named counter unless it already reached `limit`.

        Returns whether it was added. The counter may be deleted after `expire_at`."""

    def save_question(self, question_id: str, record: dict) -> None: ...

    def rate_question(self, question_id: str, rating: Rating) -> bool:
        """Store the rating on the logged question; False if there is no such question."""


class SavedAnswer(BaseModel):
    """An example question with the answer the app gave it, kept to show when the cap is hit."""

    question: str
    answer: Answer | None = None


def load_saved_answers(path: Path) -> list[SavedAnswer]:
    if not path.exists():
        return []
    return [SavedAnswer.model_validate(item) for item in json.loads(path.read_text("utf-8"))]


def save_answers(path: Path, answers: list[SavedAnswer]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump(mode="json") for item in answers]
    # newline="" keeps the line endings identical on every platform.
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def utc_now() -> datetime:
    return datetime.now(UTC)


class Demo:
    def __init__(
        self,
        store: Store,
        *,
        salt: str,
        hourly_limit: int = DEFAULT_HOURLY_LIMIT,
        daily_cap: int = DEFAULT_DAILY_CAP,
        examples: list[SavedAnswer] | None = None,
        clock: Callable[[], datetime] = utc_now,
    ):
        self._store = store
        self._salt = salt.encode()
        self._clock = clock
        self.hourly_limit = hourly_limit
        self.daily_cap = daily_cap
        self.examples = examples or []

    def admit(self, ip: str) -> Admission:
        """Count one question against the visitor's hourly limit, then the global daily cap.

        The hourly limit is checked first, so a visitor turned away by it does not use up the cap.
        Raises if the store is unreachable."""
        now = self._clock()
        hour = now.strftime("%Y%m%d%H")
        if not self._store.take(
            f"ip-{self._hash(ip)}-{hour}", self.hourly_limit, now + timedelta(hours=2)
        ):
            return "rate_limited"
        if not self._store.take(f"day-{now:%Y-%m-%d}", self.daily_cap, now + timedelta(days=2)):
            return "capped"
        return "ok"

    def rate_limited_message(self) -> str:
        noun = "question" if self.hourly_limit == 1 else "questions"
        return (
            f"You've reached the demo's limit of {self.hourly_limit} {noun} an hour."
            " Please try again later."
        )

    def log_question(
        self,
        question: str,
        outcome: Outcome,
        citations: list[str],
        latency_ms: int,
        usage: Usage,
    ) -> str | None:
        """Log one question and return its id for feedback, or None if it could not be logged."""
        now = self._clock()
        question_id = uuid.uuid4().hex
        record = {
            "question": question,
            "outcome": outcome,
            "citations": citations,
            "latency_ms": latency_ms,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "asked_at": now,
            "expire_at": now + LOG_RETENTION,
        }
        try:
            self._store.save_question(question_id, record)
        except Exception:
            log.exception("could not log the question")
            return None
        return question_id

    def rate(self, question_id: str, rating: Rating) -> bool:
        return self._store.rate_question(question_id, rating)

    def _hash(self, ip: str) -> str:
        return hmac.new(self._salt, ip.encode(), hashlib.sha256).hexdigest()[:32]
