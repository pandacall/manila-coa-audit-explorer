"""The `extract` step writes committed, human-readable records and regenerates them identically."""

import json
from pathlib import Path

from coa_explorer.cli import main

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data" / "extracted"
YEARS = range(2020, 2025)
RECORD_FILES = [
    *(f"part2/{y}.json" for y in YEARS),
    *(f"part3/{y}.json" for y in YEARS),
    *(f"executive_summary/{y}.json" for y in YEARS),
    *(f"auditors_report/{y}.json" for y in YEARS),
    "link-report.json",
]


def test_extract_writes_one_readable_record_file_per_year_and_part(tmp_path):
    assert main(["extract", "--out", str(tmp_path)]) == 0

    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json"))
    assert written == sorted(RECORD_FILES)
    record = json.loads((tmp_path / "part2" / "2024.json").read_text(encoding="utf-8"))
    assert len(record["observations"]) == 29
    assert len(record["commendations"]) == 7
    part3 = json.loads((tmp_path / "part3" / "2020.json").read_text(encoding="utf-8"))
    assert part3["table_rows"] == 55
    assert sum(len(o["recommendations"]) for o in part3["observations"]) == 79
    summary = json.loads((tmp_path / "executive_summary" / "2024.json").read_text(encoding="utf-8"))
    assert summary["page_format"] == "lowerRoman"
    assert [s["label"] for s in summary["sections"]] == list("ABCDEFG")
    report = json.loads((tmp_path / "auditors_report" / "2023.json").read_text(encoding="utf-8"))
    assert report["text_source"].startswith("reviewed transcription")
    # Human-readable: indented, with real characters rather than escapes.
    text = (tmp_path / "part2" / "2024.json").read_text(encoding="utf-8")
    assert "\n  " in text
    assert "Nature’s" in text


def test_regenerating_the_records_produces_no_diff(tmp_path):
    main(["extract", "--out", str(tmp_path / "first")])
    main(["extract", "--out", str(tmp_path / "second")])
    for name in RECORD_FILES:
        first = (tmp_path / "first" / name).read_bytes()
        assert first == (tmp_path / "second" / name).read_bytes()
        assert first == (COMMITTED / name).read_bytes(), (
            f"{name} differs from the committed record; run `coa-explorer extract` and commit"
        )


def test_the_committed_link_report_shows_every_reference_and_no_unmatched_ones():
    report = json.loads((COMMITTED / "link-report.json").read_text(encoding="utf-8"))

    assert report["counts"] == {"linked": 35, "out_of_collection": 95, "unmatched": 0}
    assert report["unmatched"] == []
    assert len(report["page_drift"]) == 35


def test_check_mode_fails_when_a_committed_record_is_stale(tmp_path):
    stale = tmp_path / "stale"
    main(["extract", "--out", str(stale)])
    assert main(["extract", "--out", str(stale), "--check"]) == 0
    (stale / "part2" / "2021.json").write_text("{}\n", encoding="utf-8")
    assert main(["extract", "--out", str(stale), "--check"]) == 1


def test_check_mode_also_covers_the_executive_summary_and_auditors_report(tmp_path):
    stale = tmp_path / "stale"
    main(["extract", "--out", str(stale)])
    (stale / "executive_summary" / "2024.json").write_text("{}\n", encoding="utf-8")
    assert main(["extract", "--out", str(stale), "--check"]) == 1
    main(["extract", "--out", str(stale)])
    (stale / "auditors_report" / "2023.json").unlink()
    assert main(["extract", "--out", str(stale), "--check"]) == 1


def test_a_changed_reviewed_transcription_changes_the_record_it_stands_in_for(tmp_path):
    reviewed = tmp_path / "reviewed"
    reviewed.mkdir()
    name = "05-ManilaCity2023_Part1-Auditor's_Report.txt"
    original = (ROOT / "data" / "reviewed" / name).read_text(encoding="utf-8")
    (reviewed / name).write_text(original.replace("P9.237 billion", "P9.999 billion"), "utf-8")

    main(["extract", "--out", str(tmp_path / "out"), "--reviewed", str(reviewed)])

    record = (tmp_path / "out" / "auditors_report" / "2023.json").read_text(encoding="utf-8")
    assert "P9.999 billion" in record
    assert main(["extract", "--out", str(tmp_path / "out"), "--check"]) == 1


def test_check_mode_also_covers_part_III_and_the_link_report(tmp_path):
    stale = tmp_path / "stale"
    main(["extract", "--out", str(stale)])
    (stale / "part3" / "2022.json").write_text("{}\n", encoding="utf-8")
    assert main(["extract", "--out", str(stale), "--check"]) == 1
    main(["extract", "--out", str(stale)])
    (stale / "link-report.json").unlink()
    assert main(["extract", "--out", str(stale), "--check"]) == 1


def test_the_links_command_prints_the_report(capsys):
    assert main(["links", "--records", str(COMMITTED)]) == 0

    output = capsys.readouterr().out
    assert "130 Part III references: 35 linked to Part II, 95 out of the collection" in output
    assert "0 unmatched" in output
    assert "drift" in output


class OneRowReader:
    """Reads every scanned page as one row that follows up CY 2023 Observation No. 1."""

    def read_page(self, pdf: bytes, document: str) -> list[dict]:
        columns = (
            "reference observations recommendations action_plan person_responsible target_from"
            " target_to status reason_for_delay action_taken follow_up_date coa_status actual_from"
            " actual_to remarks"
        ).split()
        row = dict.fromkeys(columns, "")
        row.update(reference="AAR 2023 Observation No. 1 Page 79", recommendations="Reconcile.")
        return [row]


def test_extract_aapsi_writes_a_record_per_document_and_year_and_reports_the_links(tmp_path):
    main(["extract", "--out", str(tmp_path)])

    code = main(
        ["extract-aapsi", "--out", str(tmp_path), "--passes", "1"], page_reader=OneRowReader()
    )

    assert code == 0
    written = sorted(
        p.relative_to(tmp_path).as_posix()
        for folder in ("aapsi", "apmt")
        for p in tmp_path.glob(f"{folder}/*.json")
    )
    assert written == ["aapsi/2023.json", "aapsi/2024.json", "apmt/2023.json", "apmt/2024.json"]
    apmt = json.loads((tmp_path / "apmt" / "2024.json").read_text(encoding="utf-8"))
    assert (apmt["document"], apmt["pdf_pages"]) == ("APMT", 12)
    assert apmt["observations"][0]["rows"][0]["citation"] == (
        "CY 2024 APMT, CY 2023 Observation No. 1, p. 1"
    )
    report = json.loads((tmp_path / "monitoring-link-report.json").read_text(encoding="utf-8"))
    assert report["counts"] == {"linked": 7 + 3 + 25 + 12, "out_of_collection": 0, "unmatched": 0}


def test_extract_aapsi_will_not_overwrite_reviewed_records_unless_told_to(tmp_path, capsys):
    main(["extract", "--out", str(tmp_path)])
    args = ["extract-aapsi", "--out", str(tmp_path), "--passes", "1", "--years", "2023"]
    assert main(args, page_reader=OneRowReader()) == 0
    reviewed = tmp_path / "aapsi" / "2023.json"
    reviewed.write_text('{"reviewed": true}\n', encoding="utf-8")

    assert main(args, page_reader=OneRowReader()) == 1
    assert "--overwrite" in capsys.readouterr().err
    assert reviewed.read_text(encoding="utf-8") == '{"reviewed": true}\n'
    assert main([*args, "--overwrite"], page_reader=OneRowReader()) == 0
    assert json.loads(reviewed.read_text(encoding="utf-8"))["aar_year"] == 2023


def test_the_links_command_also_prints_the_aapsi_and_apmt_references(tmp_path, capsys):
    main(["extract", "--out", str(tmp_path)])
    main(["extract-aapsi", "--out", str(tmp_path), "--passes", "1"], page_reader=OneRowReader())
    capsys.readouterr()

    assert main(["links", "--records", str(tmp_path)]) == 0

    output = capsys.readouterr().out
    assert "130 Part III references" in output
    assert "AAPSI references: 32 linked to Part II" in output
    assert "APMT references: 15 linked to Part II" in output
