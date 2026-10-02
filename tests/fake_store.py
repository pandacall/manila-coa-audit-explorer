"""An in-memory stand-in for Firestore behind the `Store` seam, recording everything it was given."""

from __future__ import annotations

from datetime import datetime


class FakeStore:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.counter_expiry: dict[str, datetime] = {}
        self.questions: dict[str, dict] = {}
        self.broken = False

    def take(self, counter: str, limit: int, expire_at: datetime) -> bool:
        self._check()
        if self.counters.get(counter, 0) >= limit:
            return False
        self.counters[counter] = self.counters.get(counter, 0) + 1
        self.counter_expiry[counter] = expire_at
        return True

    def save_question(self, question_id: str, record: dict) -> None:
        self._check()
        self.questions[question_id] = dict(record)

    def rate_question(self, question_id: str, rating: str) -> bool:
        self._check()
        if question_id not in self.questions:
            return False
        self.questions[question_id]["rating"] = rating
        return True

    def everything(self) -> str:
        """All stored keys and values as one string, to assert nothing identifying is in it."""
        return repr((self.counters, self.counter_expiry, self.questions))

    def _check(self) -> None:
        if self.broken:
            raise ConnectionError("the store is down")
