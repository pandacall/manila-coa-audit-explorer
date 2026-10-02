"""Try Document AI Layout Parser, the named fallback, on single AAPSI pages.

    uv run --group prototype python -m prototypes.aapsi.layout_parser 2023 AAPSI 6

Reports the tables it finds and their shape; the cells are saved to
results/layout/<year>_<doc>_p<page>.json so they can be read against the scan.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from google.cloud import documentai_v1 as documentai
from pypdf import PdfReader

from coa_explorer.config import load_settings
from prototypes.aapsi.extract_docai import LOCATION, client
from prototypes.aapsi.extract_gemini import page_pdf, parse_pages, pdf_path

RESULTS = Path(__file__).parent / "results" / "layout"
PROCESSOR_NAME = "coa-explorer-aapsi-layout"


def ensure_processor(c, project: str) -> str:
    parent = f"projects/{project}/locations/{LOCATION}"
    for processor in c.list_processors(parent=parent):
        if processor.display_name == PROCESSOR_NAME:
            return processor.name
    return c.create_processor(
        parent=parent,
        processor=documentai.Processor(
            display_name=PROCESSOR_NAME, type_="LAYOUT_PARSER_PROCESSOR"
        ),
    ).name


def walk(blocks) -> list:
    """All blocks, depth first, since Layout Parser nests text blocks inside lists and tables."""
    found = []
    for block in blocks:
        found.append(block)
        found += walk(block.text_block.blocks)
    return found


def table_cells(block) -> list[list[str]]:
    table = block.table_block
    rows = list(table.header_rows) + list(table.body_rows)
    return [
        [
            " ".join(
                cell.blocks[i].text_block.text
                for i in range(len(cell.blocks))
                if cell.blocks[i].text_block.text
            )
            for cell in row.cells
        ]
        for row in rows
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("doc", choices=["AAPSI", "APMT"])
    parser.add_argument("pages")
    args = parser.parse_args()

    c = client()
    processor = ensure_processor(c, load_settings().gcp_project_id)
    path = pdf_path(args.year, args.doc)
    RESULTS.mkdir(parents=True, exist_ok=True)
    for page in parse_pages(args.pages, len(PdfReader(path).pages)):
        result = c.process_document(
            request=documentai.ProcessRequest(
                name=processor,
                raw_document=documentai.RawDocument(
                    content=page_pdf(path, page), mime_type="application/pdf"
                ),
            )
        )
        blocks = walk(result.document.document_layout.blocks)
        tables = [table_cells(b) for b in blocks if b.table_block.body_rows]
        shapes = [(len(t), max((len(r) for r in t), default=0)) for t in tables]
        text_blocks = sum(1 for b in blocks if b.text_block.text)
        print(
            f"page {page}: {len(blocks)} blocks, {text_blocks} text, tables (rows, cols) {shapes}"
        )
        out = RESULTS / f"{args.year}_{args.doc}_p{page:02d}.json"
        out.write_text(
            json.dumps({"tables": tables}, indent=1, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
