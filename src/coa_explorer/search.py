"""The retrieval tools: hybrid keyword + vector `search` over the AARs, and `timeline`.

Every result carries a complete Citation. Keyword (FTS5) and vector (sqlite-vec) matches are merged
into one ranking; a hit on any piece of an Audit Observation can be expanded to the whole
observation. `timeline` follows one Audit Observation's Recommendations through the later AARs'
Part III.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import sqlite_vec

from coa_explorer.embedder import Embedder
from coa_explorer.index import load_vec_extension
from coa_explorer.timeline import Timeline, assemble_timeline

DEFAULT_LIMIT = 5  # Audit Observations per search
CANDIDATES = 50  # pieces taken from each of keyword and vector search before merging
RRF_K = 60
# Vector search always returns the nearest pieces, related or not. With gemini-embedding-001 (768
# dimensions, cosine), on-topic questions reached 0.2-0.37 and off-topic ones ("who won the
# election?") started at 0.40, so anything farther than this is noise and dropped.
MAX_VECTOR_DISTANCE = 0.4

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Piece:
    key: str  # stable id the model cites, e.g. "2023-5-description-1"
    aar_year: int
    part: str
    observation_number: int | None  # the Part II Audit Observation number; None in Part III
    origin_year: int | None  # the observation this piece is about, for a timeline
    origin_observation: int | None
    status: str | None  # COA's Status of Implementation, for a Part III piece
    kind: str
    title: str
    text: str
    page_start: int
    page_end: int
    citation: str


@dataclass(frozen=True)
class Observation:
    """One whole Audit Observation: all its pieces in reading order, and which of them matched."""

    aar_year: int
    number: int | None
    title: str
    citation: str
    pieces: list[Piece]
    matched: frozenset[str]  # keys of the pieces that matched the search


class Index:
    def __init__(self, db: sqlite3.Connection, embedder: Embedder | None = None):
        self._db = db
        self._db.row_factory = sqlite3.Row
        self._embedder = embedder
        load_vec_extension(db)
        if embedder is not None:
            (stored,) = db.execute(
                "SELECT value FROM meta WHERE key = 'embedding_dimensions'"
            ).fetchone()
            if int(stored) != embedder.dimensions:
                raise ValueError(
                    f"the index holds {stored}-dimension embeddings but the embedder makes"
                    f" {embedder.dimensions}; rebuild with `coa-explorer index`"
                )

    @classmethod
    def open(cls, path: Path, embedder: Embedder | None = None) -> Index:
        """Open the index read-only. Without an `embedder`, search is keyword-only."""
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run `coa-explorer index` first")
        return cls(
            sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False
            ),
            embedder,
        )

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Index:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def search(
        self,
        query: str,
        years: list[int] | None = None,
        parts: list[str] | None = None,
        observation: int | None = None,
        status: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> list[Piece]:
        """Matching pieces from at most `limit` Audit Observations, grouped by observation.

        Keyword and vector matches are merged into one ranking (reciprocal rank fusion). `years`,
        `parts` ("II", "III"), `observation` (a Part II observation number) and `status` (COA's
        Status of Implementation, for Part III) narrow the search; with no query words, the filters
        alone are a direct lookup, an observation filter returning that observation's pieces in
        reading order. With no `years`, observations are ordered newest year first (most relevant
        first within a year); with `years`, most relevant first.
        """
        match = fts_query(query)
        if not match and observation is None and not parts and not status:
            return []
        where, params = [], []
        if years:
            where.append(f"pieces.aar_year IN ({','.join('?' * len(years))})")
            params += years
        if parts:
            where.append(f"pieces.part IN ({','.join('?' * len(parts))})")
            params += [part.upper() for part in parts]
        if observation is not None:
            where.append("pieces.observation_number = ?")
            params.append(observation)
        if status:
            where.append("pieces.status = ?")
            params.append(status)
        if match:
            ranked = reciprocal_rank_fusion(
                self._keyword_ids(match, where, params),
                self._vector_ids(query, where, params),
            )
        else:
            ranked = self._lookup_ids(where, params)
        return group_by_observation(self._pieces(ranked), limit, newest_first=not years)

    def expand(self, pieces: list[Piece]) -> list[Observation]:
        """The whole Audit Observation behind each hit, in the order the hits first appear."""
        hits: dict[tuple, set[str]] = {}
        for piece in pieces:
            hits.setdefault(observation_key(piece), set()).add(piece.key)
        result = []
        for (year, part, number, _), matched in hits.items():
            if number is None:
                whole = [piece for piece in pieces if piece.key in matched]
            else:
                rows = self._db.execute(
                    "SELECT * FROM pieces WHERE aar_year = ? AND part = ?"
                    " AND observation_number = ? ORDER BY id",
                    (year, part, number),
                ).fetchall()
                whole = [piece_from(row) for row in rows]
            result.append(
                Observation(
                    aar_year=year,
                    number=number,
                    title=whole[0].title,
                    citation=whole[0].citation,
                    pieces=whole,
                    matched=frozenset(matched),
                )
            )
        return result

    def _keyword_ids(self, match: str, where: list[str], params: list) -> list[int]:
        rows = self._db.execute(
            "SELECT pieces.id FROM pieces_fts JOIN pieces ON pieces.id = pieces_fts.rowid"
            f" WHERE {' AND '.join(['pieces_fts MATCH ?', *where])}"
            " ORDER BY bm25(pieces_fts) LIMIT ?",
            [match, *params, CANDIDATES],
        ).fetchall()
        return [row[0] for row in rows]

    def _vector_ids(self, query: str, where: list[str], params: list) -> list[int]:
        if self._embedder is None:
            return []
        try:
            vector = self._embedder.embed_query(query)
        except Exception:
            # Keyword results alone still make a cited answer, so degrade instead of failing.
            log.warning("embedding the query failed; using keyword results only", exc_info=True)
            return []
        restrict = ""
        if where:
            restrict = f" AND rowid IN (SELECT id FROM pieces WHERE {' AND '.join(where)})"
        rows = self._db.execute(
            f"SELECT rowid, distance FROM pieces_vec WHERE embedding MATCH ? AND k = ?{restrict}"
            " ORDER BY distance",
            [sqlite_vec.serialize_float32(vector), CANDIDATES, *params],
        ).fetchall()
        return [row[0] for row in rows if row[1] <= MAX_VECTOR_DISTANCE]

    def _lookup_ids(self, where: list[str], params: list) -> list[int]:
        rows = self._db.execute(
            f"SELECT id FROM pieces WHERE {' AND '.join(where)} ORDER BY aar_year DESC, id LIMIT ?",
            [*params, CANDIDATES],
        ).fetchall()
        return [row[0] for row in rows]

    def _pieces(self, ids: list[int]) -> list[Piece]:
        """The pieces with these ids, in the given order."""
        if not ids:
            return []
        rows = self._db.execute(
            f"SELECT * FROM pieces WHERE id IN ({','.join('?' * len(ids))})", ids
        ).fetchall()
        by_id = {row["id"]: piece_from(row) for row in rows}
        return [by_id[i] for i in ids]

    def piece(self, key: str) -> Piece | None:
        row = self._db.execute("SELECT * FROM pieces WHERE key = ?", (key,)).fetchone()
        return piece_from(row) if row else None

    def timeline(self, origin_year: int, origin_observation: int) -> Timeline | None:
        """How COA's Status of Implementation for one Audit Observation's Recommendations changed
        in each later AAR, or None if neither Part II nor any Part III mentions it."""
        return assemble_timeline(self._db, origin_year, origin_observation)


def reciprocal_rank_fusion(*rankings: list[int]) -> list[int]:
    """Merge ranked id lists: an id scores the sum of 1/(K + rank) over the lists it appears in."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(scores, key=lambda item: -scores[item])


def observation_key(piece: Piece) -> tuple:
    """What a piece is part of: a Part II observation, or the earlier observation a Part III block
    of rows follows up (Part III pieces have no observation number of their own)."""
    origin = (
        (piece.origin_year, piece.origin_observation) if piece.observation_number is None else None
    )
    return (piece.aar_year, piece.part, piece.observation_number, origin)


def group_by_observation(pieces: list[Piece], limit: int, *, newest_first: bool) -> list[Piece]:
    """Keep the `limit` best-ranked observations, their hits together; optionally newest first."""
    groups: dict[tuple, list[Piece]] = {}
    for piece in pieces:
        key = observation_key(piece)
        if key not in groups and len(groups) == limit:
            continue
        groups.setdefault(key, []).append(piece)
    ordered = list(groups.values())
    if newest_first:
        ordered.sort(key=lambda group: -group[0].aar_year)  # stable: ties stay in rank order
    return [piece for group in ordered for piece in group]


def piece_from(row: sqlite3.Row) -> Piece:
    return Piece(**{name: row[name] for name in Piece.__dataclass_fields__})


def fts_query(text: str) -> str:
    """Turn free text into an FTS5 query: every word quoted (so operators are inert), OR-ed.

    With several words the whole phrase is added too, so an exact term such as "IPSAS 1" outranks
    pieces that merely contain "IPSAS" and "1" somewhere.
    """
    words = re.findall(r"\w+", text)
    terms = [f'"{word}"' for word in words]
    if len(words) > 1:
        terms.insert(0, f'"{" ".join(words)}"')
    return " OR ".join(terms)
