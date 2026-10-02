"""A deterministic fake embedder: hashed bag-of-words plus a few hand-made synonym groups.

Texts that share a word, or two words from one synonym group, get nearby vectors; texts that share
nothing are orthogonal. That is enough to show vector hits that keyword search cannot make.
"""

from __future__ import annotations

import hashlib
import math
import re

DIMENSIONS = 256

CONCEPT_WEIGHT = 5.0  # a shared concept counts for more than a shared common word

# Everyday words that mean the same as COA's wording, so a plain-language question can reach it.
SYNONYMS = {
    "unliquidated": "concept-unsettled-advances",
    "unsettled": "concept-unsettled-advances",
    "outstanding": "concept-unsettled-advances",
    "unreconciled": "concept-bank-mismatch",
    "mismatch": "concept-bank-mismatch",
    "mismatched": "concept-bank-mismatch",
    "reconciled": "concept-bank-mismatch",
    "reconciliation": "concept-bank-mismatch",
}


class FakeEmbedder:
    dimensions = DIMENSIONS

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vectorise(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return vectorise(text)


def vectorise(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in re.findall(r"\w+", text.lower()):
        token = SYNONYMS.get(word, word)
        slot = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % DIMENSIONS
        vector[slot] += CONCEPT_WEIGHT if word in SYNONYMS else 1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]
