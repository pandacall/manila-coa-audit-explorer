"""The demo's `Store` on Firestore, in the app's own named database (see scripts/setup-gcp.sh).

Credentials are Application Default Credentials locally and the service account on Cloud Run.
Documents are deleted by Firestore's TTL policy once their TTL field passes: question records and
counters both carry it. Not unit-tested against Firestore itself; the demo logic is tested through
the same `Store` interface with a fake.
"""

from __future__ import annotations

from datetime import datetime

from google.api_core.exceptions import NotFound
from google.cloud import firestore


class FirestoreStore:
    def __init__(
        self,
        *,
        project: str,
        database: str,
        questions_collection: str = "questions",
        counters_collection: str = "limits",
        ttl_field: str = "expire_at",
    ):
        self._db = firestore.Client(project=project, database=database)
        self._questions = self._db.collection(questions_collection)
        self._counters = self._db.collection(counters_collection)
        self._ttl_field = ttl_field

    def take(self, counter: str, limit: int, expire_at: datetime) -> bool:
        # A transaction, so concurrent instances can never both take the last slot.
        ref = self._counters.document(counter)
        return _take(self._db.transaction(), ref, limit, {self._ttl_field: expire_at})

    def save_question(self, question_id: str, record: dict) -> None:
        record = dict(record)
        record[self._ttl_field] = record.pop("expire_at")
        self._questions.document(question_id).set(record)

    def rate_question(self, question_id: str, rating: str) -> bool:
        try:
            self._questions.document(question_id).update({"rating": rating})
        except NotFound:
            return False
        return True


@firestore.transactional
def _take(transaction, ref, limit: int, expiry: dict) -> bool:
    snapshot = ref.get(transaction=transaction)
    count = snapshot.get("count") if snapshot.exists else 0
    if count >= limit:
        return False
    transaction.set(ref, {"count": count + 1, **expiry})
    return True
