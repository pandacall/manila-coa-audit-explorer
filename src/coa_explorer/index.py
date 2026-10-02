"""Build the single SQLite index file (ADR-0002) from the extracted records.

An Audit Observation becomes several pieces that share its identity (AAR year, observation number,
Citation): its description, its Recommendations, its Management Comment and, when COA has one, its
Auditor's Rejoinder. Long descriptions are split on paragraph boundaries so a piece stays small
enough to read in full.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import sqlite_vec

from coa_explorer.embedder import Embedder

MAX_PIECE_CHARS = 1800

SCHEMA = """
CREATE TABLE pieces (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    aar_year INTEGER NOT NULL,
    part TEXT NOT NULL,
    observation_number INTEGER,
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
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def load_vec_extension(db: sqlite3.Connection) -> None:
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)


def build_index(records_dir: Path, db_path: Path, embedder: Embedder) -> int:
    """Index every `<year>.json` in `records_dir` into a fresh SQLite file, returning the count.

    Each piece is stored for keyword search (FTS5) and, embedded by `embedder`, for vector search
    (sqlite-vec).
    """
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
        for path in sorted(records_dir.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            for observation in record["observations"]:
                db.executemany(
                    "INSERT INTO pieces (key, aar_year, part, observation_number, kind, title,"
                    " text, page_start, page_end, citation)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            f"{observation['aar_year']}-{observation['number']}-{kind}-{seq}",
                            observation["aar_year"],
                            "II",
                            observation["number"],
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
