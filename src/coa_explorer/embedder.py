"""The embedder interface and its Gemini implementation.

Documents and queries are embedded differently (Gemini takes a task type for each), so the
interface keeps them apart. Vectors are stored in the index with the embedder's dimension; an index
and an embedder of different dimensions cannot be used together.
"""

from __future__ import annotations

from typing import Protocol

from google import genai
from google.genai import types

# gemini-embedding-001 produces 3072 dimensions by default; 768 keeps the shipped file small with
# little loss for a corpus this size.
DIMENSIONS = 768
BATCH_SIZE = 100


class Embedder(Protocol):
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    def __init__(self, *, project: str, location: str, model: str, dimensions: int = DIMENSIONS):
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors += self._embed(texts[start : start + BATCH_SIZE], "RETRIEVAL_DOCUMENT")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        response = self._client.models.embed_content(
            model=self._model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=self.dimensions
            ),
        )
        return [list(embedding.values) for embedding in response.embeddings]
