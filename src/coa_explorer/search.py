"""The retrieval tools: `search` over pieces of the AARs, each with a complete Citation, and
`timeline` for how one Audit Observation's Recommendations were followed up across years."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from coa_explorer.timeline import FollowUp, Raised, Step, Timeline

MAX_TIMELINE_TITLE_CHARS = 200


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
        parts: list[str] | None = None,
        status: str | None = None,
        limit: int = 8,
    ) -> list[Piece]:
        """Ranked pieces matching `query`, optionally within `years`, one Part II observation
        number, `parts` ("II", "III") and, for Part III, one Status of Implementation.

        With no query words, the filters alone return matching pieces newest AAR first; an
        observation filter returns that observation's pieces in reading order.
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
            params += parts
        if observation is not None:
            where.append("pieces.observation_number = ?")
            params.append(observation)
        if status:
            where.append("pieces.status = ?")
            params.append(status)
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

    def piece(self, key: str) -> Piece | None:
        row = self._db.execute("SELECT * FROM pieces WHERE key = ?", (key,)).fetchone()
        return piece_from(row) if row else None

    def timeline(self, origin_year: int, origin_observation: int) -> Timeline | None:
        """How COA's Status of Implementation for one Audit Observation's Recommendations changed
        in each later AAR, or None if neither Part II nor any Part III mentions it.

        An observation that predates the collection still gets a timeline, cited to the 2020-2024
        AARs whose Part III track it.
        """
        follow_ups = self._db.execute(
            "SELECT * FROM follow_ups WHERE origin_year = ? AND origin_observation = ?"
            " ORDER BY tracked_in, number",
            (origin_year, origin_observation),
        ).fetchall()
        raised = self._db.execute(
            "SELECT key, citation, title FROM pieces WHERE part = 'II' AND aar_year = ?"
            " AND observation_number = ? ORDER BY id LIMIT 1",
            (origin_year, origin_observation),
        ).fetchone()
        if not follow_ups and not raised:
            return None
        steps: list[Step] = []
        for row in follow_ups:
            if not steps or steps[-1].aar_year != row["tracked_in"]:
                steps.append(Step(aar_year=row["tracked_in"], follow_ups=[]))
            steps[-1].follow_ups.append(
                FollowUp(
                    key=row["key"],
                    recommendation=row["recommendation"],
                    status=row["status"],
                    status_text=row["status_text"],
                    status_note=row["status_note"],
                    management_action=row["management_action"],
                    reason=row["reason"],
                    shared=json.loads(row["shared"]),
                    citation=row["citation"],
                )
            )
        title = clip(raised["title"] if raised else follow_ups[0]["summary"])
        return Timeline(
            origin_year=origin_year,
            origin_observation=origin_observation,
            title=title,
            in_collection=raised is not None,
            raised=Raised(**dict(raised)) if raised else None,
            steps=steps,
        )


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


def clip(text: str, limit: int = MAX_TIMELINE_TITLE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
