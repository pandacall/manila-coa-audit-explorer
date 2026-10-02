"""Build the single SQLite index file (ADR-0002) from the extracted records.

An Audit Observation becomes several pieces that share its identity (AAR year, observation number,
Citation): its description, its Recommendations, its Management Comment and, when COA has one, its
Auditor's Rejoinder. Long descriptions are split on paragraph boundaries so a piece stays small
enough to read in full.

The Executive Summary (part "ES"), the Auditor's Report (part "I", its place in the AAR), the
transmittal letter (part "TL") and the Management Responsibility statement (part "MR") become one
piece per section, split on paragraph boundaries when long; a heading with no text makes none. Each
carries the section's Citation. The letter and the statement have one section each, the whole
document. (The codes are document codes, not all of them COA Parts.)

The Financial Statements and Annexes are not pieces: every amount goes to the `financial_lines`
table, in centavos, for `financial_lookup`.

Each Prior Years' Recommendation in Part III becomes one piece (COA's Status of Implementation with
Management's action and reason), plus a row in `follow_ups`. Each AAPSI row (Management's Action
Plan and Reported Status) and each APMT row (COA's validation) becomes one piece, plus a row in
`monitoring_rows`; every part of their text is labelled with whose words it is, and a piece's
`status` is COA's Status of Implementation only, so an AAPSI piece never has one. The `links` table
records, for every block of Part III, AAPSI and APMT rows, the Originating Observation it names and
whether it lies in the collection; timelines are assembled from these tables and the Part II
pieces.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import sqlite_vec

from coa_explorer.aapsi import DOCUMENTS
from coa_explorer.embedder import Embedder
from coa_explorer.front_matter import (
    AUDITORS_REPORT,
    EXECUTIVE_SUMMARY,
    MANAGEMENT_RESPONSIBILITY,
    TRANSMITTAL_LETTER,
)
from coa_explorer.links import build_links
from coa_explorer.timeline import clip_title, disagreement

MAX_PIECE_CHARS = 1800

# Each document that is read in sections: its record folder (also its piece kind) and part code.
FRONT_MATTER = {
    EXECUTIVE_SUMMARY: ("executive_summary", "ES"),
    AUDITORS_REPORT: ("auditors_report", "I"),
    TRANSMITTAL_LETTER: ("transmittal_letter", "TL"),
    MANAGEMENT_RESPONSIBILITY: ("management_responsibility", "MR"),
}

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
    derived_end INTEGER,
    document TEXT NOT NULL
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
CREATE TABLE monitoring_rows (
    key TEXT PRIMARY KEY,
    document TEXT NOT NULL,
    aar_year INTEGER NOT NULL,
    number INTEGER NOT NULL,
    origin_year INTEGER,
    origin_observation INTEGER,
    summary TEXT NOT NULL,
    recommendation TEXT,
    action_plan TEXT,
    person_responsible TEXT,
    target_from TEXT,
    target_to TEXT,
    reported_status_text TEXT,
    reported_status TEXT,
    reason TEXT,
    action_taken TEXT,
    follow_up_date TEXT,
    status_text TEXT,
    status TEXT,
    actual_from TEXT,
    actual_to TEXT,
    remarks TEXT,
    citation TEXT NOT NULL
);
CREATE TABLE financial_lines (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    aar_year INTEGER NOT NULL,
    source TEXT NOT NULL,
    statement TEXT NOT NULL,
    sheet TEXT NOT NULL,
    sheet_row INTEGER NOT NULL,
    fund TEXT NOT NULL,
    section TEXT NOT NULL,
    line_item TEXT NOT NULL,
    column_name TEXT NOT NULL,
    period INTEGER NOT NULL,
    centavos INTEGER NOT NULL,
    citation TEXT NOT NULL
);
CREATE INDEX financial_lines_year ON financial_lines (aar_year, statement);
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


def load_monitoring(records_dir: Path) -> dict[str, dict[int, dict]]:
    """The AAPSI and APMT records under `aapsi/` and `apmt/`, keyed by document then AAR year."""
    return {document: load_records(records_dir / document.lower()) for document in DOCUMENTS}


MONITORING_COLUMNS = (
    "recommendation action_plan person_responsible target_from target_to reported_status_text"
    " reported_status reason action_taken follow_up_date status_text status actual_from actual_to"
    " remarks citation"
).split()


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
        record
        for folder, _ in FRONT_MATTER.values()
        for record in load_records(records_dir / folder).values()
    ]
    monitoring = load_monitoring(records_dir)
    financial = load_records(records_dir / "financial")
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
        for document, records in monitoring.items():
            for record in records.values():
                for block in record["observations"]:
                    for row in block["rows"]:
                        add_monitoring_row(db, record["aar_year"], document, block, row)
        for record in financial.values():
            add_financial_lines(db, record)
        for link in build_links(part2, part3, monitoring):
            db.execute(
                "INSERT INTO links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    link.document,
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


def add_financial_lines(db: sqlite3.Connection, record: dict) -> None:
    """The financial lines of one AAR, each amount in whole centavos so that sums are exact."""
    db.executemany(
        "INSERT INTO financial_lines (key, aar_year, source, statement, sheet, sheet_row, fund,"
        " section, line_item, column_name, period, centavos, citation)"
        f" VALUES ({', '.join('?' * 13)})",
        [
            (
                line["key"],
                record["aar_year"],
                line["source"],
                line["statement"],
                line["sheet"],
                line["row"],
                line["fund"],
                line["section"],
                line["line_item"],
                line["column"],
                line["period"],
                int(Decimal(line["amount"]) * 100),
                line["citation"],
            )
            for line in record["lines"]
        ],
    )


def front_matter_pieces(record: dict) -> Iterator[tuple]:
    """The piece rows of one Executive Summary, Auditor's Report, transmittal letter or Management
    Responsibility statement, a section at a time."""
    year, document = record["aar_year"], record["document"]
    kind, part = FRONT_MATTER[document]
    for number, section in enumerate(record["sections"], start=1):
        # The Executive Summary's sections are lettered, the Auditor's Report's are numbered "AR-n"
        # (the key ids the model cites), and the one-section documents are just "n".
        if document == EXECUTIVE_SUMMARY:
            anchor = section["label"]
        elif document == AUDITORS_REPORT:
            anchor = f"AR-{number}"
        else:
            anchor = str(number)
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


def add_monitoring_row(
    db: sqlite3.Connection, year: int, document: str, block: dict, row: dict
) -> None:
    key = f"{year}-{document}-{row['number']}"
    db.execute(
        PIECE_INSERT,
        (
            key,
            year,
            document,
            None,
            block["origin_year"],
            block["origin_observation"],
            row["status"],  # COA's, so None for an AAPSI row, which has none
            "action_plan" if document == "AAPSI" else "coa_validation",
            clip_title(block["summary"] or block["reference"] or document),
            monitoring_text(document, block, row),
            row["page"],
            row["page"],
            row["citation"],
        ),
    )
    db.execute(
        f"INSERT INTO monitoring_rows (key, document, aar_year, number, origin_year,"
        f" origin_observation, summary, {', '.join(MONITORING_COLUMNS)})"
        f" VALUES ({', '.join('?' * (7 + len(MONITORING_COLUMNS)))})",
        (
            key,
            document,
            year,
            row["number"],
            block["origin_year"],
            block["origin_observation"],
            block["summary"],
            *(row[name] for name in MONITORING_COLUMNS),
        ),
    )


def monitoring_text(document: str, block: dict, row: dict) -> str:
    """The searchable text of one AAPSI or APMT row, each part labelled with whose words it is.

    The AAPSI's columns are Management's account; in the APMT the same columns are Management's and
    only the validation columns are COA's. A disagreement between the two statuses is said outright.
    """
    if block["origin_year"] is None or block["origin_observation"] is None:
        origin = block["reference"] or "no Reference printed"
    else:
        origin = f"CY {block['origin_year']} AAR, Observation No. {block['origin_observation']}"
    lines = [
        f"Management's Action Plan (AAPSI): {origin}"
        if document == "AAPSI"
        else f"COA's Action Plan Monitoring Tool (APMT): {origin}"
    ]
    coa: list[tuple[str, str | None]] = []
    if document == "APMT":
        coa = [
            ("Status of Implementation (COA)", row["status_text"]),
            ("Date of COA's follow-up", row["follow_up_date"]),
            ("Actual implementation date (COA)", dates(row["actual_from"], row["actual_to"])),
            ("COA's remarks", row["remarks"]),
        ]
    said = disagreement(row["reported_status"], row["status"])
    management = [
        ("Action Plan (Management)", row["action_plan"]),
        ("Person or department responsible (Management)", row["person_responsible"]),
        ("Target implementation (Management)", dates(row["target_from"], row["target_to"])),
        ("Reported Status (Management)", row["reported_status_text"]),
        (
            "Reason for partial implementation, delay or non-implementation (Management)",
            row["reason"],
        ),
        ("Action taken or to be taken (Management)", row["action_taken"]),
    ]
    lines += [
        f"{label}: {value}"
        for label, value in [
            ("Observation", block["summary"]),
            ("Recommendation", row["recommendation"]),
            *coa,
            (
                "Reported Status and Status of Implementation disagree",
                f"{said}." if said else None,
            ),
            *management,
        ]
        if value
    ]
    return "\n".join(lines)


def dates(start: str | None, end: str | None) -> str | None:
    """A target or actual period as printed: "2023 to 2024", or whichever of the two is given."""
    return " to ".join(d for d in (start, end) if d) or None


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
