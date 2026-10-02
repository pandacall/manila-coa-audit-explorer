"""Build the single SQLite index file (ADR-0002) from the extracted records.

An Audit Observation becomes several pieces that share its identity (AAR year, observation number,
Citation): its description, its Recommendations, its Management Comment and, when COA has one, its
Auditor's Rejoinder. Long descriptions are split on paragraph boundaries so a piece stays small
enough to read in full.

The Executive Summary (part "ES") and the Auditor's Report (part "I", its place in the AAR) become
one piece per section, split on paragraph boundaries when long; a heading with no text makes none.
Each carries the section's Citation.

Each Prior Years' Recommendation in Part III becomes one piece (COA's Status of Implementation with
Management's action and reason), plus a row in `follow_ups`. The `links` table records, for every
block of Part III rows, the Originating Observation it names and whether it lies in the collection;
timelines are assembled from these two tables and the Part II pieces.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import sqlite_vec

from coa_explorer.embedder import Embedder
from coa_explorer.front_matter import EXECUTIVE_SUMMARY
from coa_explorer.links import build_links
from coa_explorer.timeline import clip_title

MAX_PIECE_CHARS = 1800

SCHEMA = """
CREATE TABLE pieces (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    aar_year INTEGER NOT NULL,
    part TEXT NOT NULL,
    observation_number INTEGER,
    origin_year INTEGER,
    origin_observation INTEGER,
    status TEXT,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    page_start INTEGER NOT NULL,
    page_end INTEGER NOT NULL,
    citation TEXT NOT NULL
);
CREATE VIRTUAL TABLE pieces_fts USING fts5(
    title, text, content='pieces', content_rowid='id', tokenize='porter unicode61'
);
CREATE TABLE links (
    tracked_in INTEGER NOT NULL,
    reference TEXT NOT NULL,
    origin_year INTEGER,
    origin_observation INTEGER,
    outcome TEXT NOT NULL,
    reason TEXT,
    origin_citation TEXT,
    cited_start INTEGER,
    cited_end INTEGER,
    derived_start INTEGER,
    derived_end INTEGER
);
CREATE TABLE follow_ups (
    key TEXT PRIMARY KEY,
    tracked_in INTEGER NOT NULL,
    number INTEGER NOT NULL,
    origin_year INTEGER,
    origin_observation INTEGER,
    summary TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    status TEXT NOT NULL,
    status_text TEXT NOT NULL,
    status_note TEXT,
    management_action TEXT,
    reason TEXT,
    shared TEXT NOT NULL,
    citation TEXT NOT NULL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

PIECE_COLUMNS = (
    "key, aar_year, part, observation_number, origin_year, origin_observation, status, kind,"
    " title, text, page_start, page_end, citation"
)


PIECE_INSERT = f"INSERT INTO pieces ({PIECE_COLUMNS}) VALUES ({', '.join('?' * 13)})"


def load_records(directory: Path) -> dict[int, dict]:
    """The `<year>.json` records in `directory` keyed by AAR year; empty if there is none."""
    return {
        int(path.stem): json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    }


def load_vec_extension(db: sqlite3.Connection) -> None:
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)


def build_index(records_dir: Path, db_path: Path, embedder: Embedder) -> int:
    """Index the records under `records_dir` (`part2/`, `part3/`) into a fresh SQLite file.

    Each piece is stored for keyword search (FTS5) and, embedded by `embedder`, for vector search
    (sqlite-vec). Returns the number of pieces.
    """
    part2 = load_records(records_dir / "part2")
    part3 = load_records(records_dir / "part3")
    front_matter = [
        *load_records(records_dir / "executive_summary").values(),
        *load_records(records_dir / "auditors_report").values(),
    ]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as db:
        load_vec_extension(db)
        db.executescript(SCHEMA)
        db.execute(
            "CREATE VIRTUAL TABLE pieces_vec USING vec0("
            f"embedding float[{embedder.dimensions}] distance_metric=cosine)"
        )
        db.execute(
            "INSERT INTO meta VALUES ('embedding_dimensions', ?)", (str(embedder.dimensions),)
        )
        for record in part2.values():
            for observation in record["observations"]:
                db.executemany(
                    PIECE_INSERT,
                    [
                        (
                            f"{observation['aar_year']}-{observation['number']}-{kind}-{seq}",
                            observation["aar_year"],
                            "II",
                            observation["number"],
                            observation["aar_year"],
                            observation["number"],
                            None,
                            kind,
                            observation["title"],
                            text,
                            observation["page_start"],
                            observation["page_end"],
                            observation["citation"],
                        )
                        for kind, seq, text in observation_pieces(observation)
                    ],
                )
        for record in front_matter:
            db.executemany(PIECE_INSERT, front_matter_pieces(record))
        for record in part3.values():
            for tracked in record["observations"]:
                for rec in tracked["recommendations"]:
                    add_follow_up(db, record["aar_year"], tracked, rec)
        for link in build_links(part2, part3):
            db.execute(
                "INSERT INTO links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    link.tracked_in,
                    link.reference,
                    link.origin_year,
                    link.origin_observation,
                    link.outcome,
                    link.reason,
                    link.origin_citation,
                    *(link.cited_pages or (None, None)),
                    *(link.derived_pages or (None, None)),
                ),
            )
        db.execute("INSERT INTO pieces_fts(rowid, title, text) SELECT id, title, text FROM pieces")
        rows = db.execute("SELECT id, title, text FROM pieces ORDER BY id").fetchall()
        vectors = embedder.embed_documents([f"{title}\n{text}" for _, title, text in rows])
        db.executemany(
            "INSERT INTO pieces_vec(rowid, embedding) VALUES (?, ?)",
            [
                (row_id, sqlite_vec.serialize_float32(vector))
                for (row_id, _, _), vector in zip(rows, vectors, strict=True)
            ],
        )
        (count,) = db.execute("SELECT count(*) FROM pieces").fetchone()
    db.close()
    return count


def front_matter_pieces(record: dict) -> Iterator[tuple]:
    """The piece rows of one Executive Summary or Auditor's Report, a section at a time."""
    year, document = record["aar_year"], record["document"]
    summary = document == EXECUTIVE_SUMMARY
    part, kind = ("ES", "executive_summary") if summary else ("I", "auditors_report")
    for number, section in enumerate(record["sections"], start=1):
        anchor = section["label"] if summary else f"AR-{number}"
        for seq, text in enumerate(split_text(section["text"]), start=1):
            yield (
                f"{year}-{part}-{anchor}-{seq}",
                year,
                part,
                None,
                None,
                None,
                None,
                kind,
                f"{document}: {section['heading']}",
                text,
                section["page_start"],
                section["page_end"],
                section["citation"],
            )


def add_follow_up(db: sqlite3.Connection, year: int, tracked: dict, rec: dict) -> None:
    key = f"{year}-III-{rec['number']}"
    db.execute(
        PIECE_INSERT,
        (
            key,
            year,
            "III",
            None,
            tracked["origin_year"],
            tracked["origin_observation"],
            rec["status"],
            "prior_years_recommendation",
            clip_title(tracked["summary"]),
            follow_up_text(tracked, rec),
            rec["page_start"],
            rec["page_end"],
            rec["citation"],
        ),
    )
    db.execute(
        "INSERT INTO follow_ups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key,
            year,
            rec["number"],
            tracked["origin_year"],
            tracked["origin_observation"],
            tracked["summary"],
            rec["recommendation"],
            rec["status"],
            rec["status_text"],
            rec["status_note"],
            rec["management_action"],
            rec["reason"],
            json.dumps(rec["shared"]),
            rec["citation"],
        ),
    )


def follow_up_text(tracked: dict, rec: dict) -> str:
    """The searchable text of one Part III row, each part labelled with whose words it is."""
    status = rec["status_text"] + (f" ({rec['status_note']})" if rec["status_note"] else "")
    lines = [
        f"Prior Years' Recommendation: CY {tracked['origin_year']} AAR,"
        f" Observation No. {tracked['origin_observation']}",
        f"Observation: {tracked['summary']}",
        f"Recommendation: {rec['recommendation']}",
        f"Status of Implementation (COA): {status}",
    ]
    if rec["management_action"]:
        lines.append(f"Management action: {rec['management_action']}")
    if rec["reason"]:
        lines.append(f"Reason for partial or non-implementation: {rec['reason']}")
    return "\n".join(lines)


def observation_pieces(observation: dict) -> Iterator[tuple[str, int, str]]:
    """(kind, sequence within the kind, text) for each piece of one Audit Observation."""
    for seq, text in enumerate(split_text(observation["description"]), start=1):
        yield "description", seq, text
    if observation["recommendations"]:
        yield "recommendations", 1, recommendations_text(observation["recommendations"])
    if observation["management_comment"]:
        yield "management_comment", 1, observation["management_comment"]
    if observation["auditors_rejoinder"]:
        yield "auditors_rejoinder", 1, observation["auditors_rejoinder"]


def recommendations_text(recommendations: list[dict]) -> str:
    """Each distinct lead-in once, followed by the items that complete it."""
    lines: list[str] = []
    lead_in = None
    for item in recommendations:
        if item["lead_in"] and item["lead_in"] != lead_in:
            lines.append(item["lead_in"])
        lead_in = item["lead_in"]
        lines.append(f"{item['label']} {item['text']}" if item["label"] else item["text"])
    return "\n".join(lines)


def split_text(text: str, limit: int = MAX_PIECE_CHARS) -> Iterator[str]:
    """Split on paragraph boundaries into pieces of at most `limit` characters where possible."""
    current = ""
    for paragraph in (p for p in text.split("\n") if p.strip()):
        if current and len(current) + len(paragraph) + 1 > limit:
            yield current
            current = ""
        current = f"{current}\n{paragraph}" if current else paragraph
    if current:
        yield current
