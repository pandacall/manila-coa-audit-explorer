"""The `extract` step writes committed, human-readable records and regenerates them identically."""

import json
from pathlib import Path

from coa_explorer.cli import main

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data" / "extracted" / "part2"


def test_extract_writes_one_readable_record_file_per_year(tmp_path):
    assert main(["extract", "--out", str(tmp_path)]) == 0

    assert sorted(p.name for p in tmp_path.glob("*.json")) == [
        f"{y}.json" for y in range(2020, 2025)
    ]
    record = json.loads((tmp_path / "2024.json").read_text(encoding="utf-8"))
    assert len(record["observations"]) == 29
    assert len(record["commendations"]) == 7
    # Human-readable: indented, with real characters rather than escapes.
    text = (tmp_path / "2024.json").read_text(encoding="utf-8")
    assert "\n  " in text
    assert "Nature’s" in text


def test_regenerating_the_records_produces_no_diff(tmp_path):
    main(["extract", "--out", str(tmp_path / "first")])
    main(["extract", "--out", str(tmp_path / "second")])
    for year in range(2020, 2025):
        first = (tmp_path / "first" / f"{year}.json").read_bytes()
        assert first == (tmp_path / "second" / f"{year}.json").read_bytes()
        assert first == (COMMITTED / f"{year}.json").read_bytes(), (
            f"{year}.json differs from the committed record; run `coa-explorer extract` and commit"
        )


def test_check_mode_fails_when_a_committed_record_is_stale(tmp_path):
    stale = tmp_path / "stale"
    main(["extract", "--out", str(stale)])
    assert main(["extract", "--out", str(stale), "--check"]) == 0
    (stale / "2021.json").write_text("{}\n", encoding="utf-8")
    assert main(["extract", "--out", str(stale), "--check"]) == 1
