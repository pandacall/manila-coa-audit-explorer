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
