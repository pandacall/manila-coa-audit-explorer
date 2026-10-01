"""The `search` retrieval tool: ranked pieces of the AARs, each with a complete Citation."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Piece:
    key: str  # stable id the model cites, e.g. "2023-5-description-1"
    aar_year: int
    part: str
    observation_number: int | None
    kind: str
    title: str
    text: str
    page_start: int
    page_end: int
    citation: str


class Index:
    def __init__(self, db: sqlite3.Connection):
        self._db = db
        self._db.row_factory = sqlite3.Row

    @classmethod
    def open(cls, path: Path) -> Index:
        if not path.exists():
            raise FileNotFoundError(f"{path} not found; run `coa-explorer index` first")
        return cls(
            sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
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
        observation: int | None = None,
        limit: int = 8,
    ) -> list[Piece]:
        """Ranked pieces matching `query`, optionally within `years` and one observation number.

        With no query words, an observation filter alone returns that observation's pieces in
        reading order.
        """
        match = fts_query(query)
        if not match and observation is None:
            return []
        where, params = [], []
        if years:
            where.append(f"pieces.aar_year IN ({','.join('?' * len(years))})")
            params += years
        if observation is not None:
            where.append("pieces.observation_number = ?")
            params.append(observation)
        if match:
            sql = "SELECT pieces.* FROM pieces_fts JOIN pieces ON pieces.id = pieces_fts.rowid"
            where.insert(0, "pieces_fts MATCH ?")
            params.insert(0, match)
            order = "bm25(pieces_fts)"
        else:
            sql = "SELECT pieces.* FROM pieces"
            order = "pieces.aar_year DESC, pieces.id"
        sql += f" WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?"
        rows = self._db.execute(sql, [*params, limit]).fetchall()
        return [piece_from(row) for row in rows]


def piece_from(row: sqlite3.Row) -> Piece:
    return Piece(**{name: row[name] for name in Piece.__dataclass_fields__})


def fts_query(text: str) -> str:
    """Turn free text into an FTS5 query: every word quoted (so operators are inert), OR-ed."""
    words = re.findall(r"\w+", text)
    return " OR ".join(f'"{word}"' for word in words)
