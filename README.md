# COA Audit Explorer

Plain-language, cited answers to questions about the Commission on Audit's Annual Audit Reports
on the City of Manila, 2020-2024. See `CONTEXT.md` for the project vocabulary and `docs/adr/` for
design decisions.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Extracting Part II

```bash
uv run coa-explorer extract
```

Reads each year's Part II (Audit Observations and Recommendations) Word file under
`coa-audit-reports/` and writes one committed, human-readable JSON file per year to
`data/extracted/part2/`. Re-running produces no diff.
