"""Run AAPSI pages through Document AI Enterprise OCR and keep the words with their positions.

    uv run --group prototype python -m prototypes.aapsi.extract_docai 2023 AAPSI 2

Enterprise OCR returns text and word boxes, not table cells; assigning words to cells is done in
report.py. Creates the OCR processor on first use and reuses it after. Writes
prototypes/aapsi/results/docai/<year>_<doc>_p<page>.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from google.cloud import documentai_v1 as documentai
from pypdf import PdfReader

from coa_explorer.config import load_settings
from prototypes.aapsi.extract_gemini import page_pdf, parse_pages, pdf_path

RESULTS = Path(__file__).parent / "results" / "docai"
LOCATION = "us"  # Document AI is multi-region (us/eu), not us-central1
PROCESSOR_NAME = "coa-explorer-aapsi-ocr"


def client() -> documentai.DocumentProcessorServiceClient:
    return documentai.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{LOCATION}-documentai.googleapis.com"}
    )


def ensure_processor(c: documentai.DocumentProcessorServiceClient, project: str) -> str:
    parent = f"projects/{project}/locations/{LOCATION}"
    for processor in c.list_processors(parent=parent):
        if processor.display_name == PROCESSOR_NAME:
            return processor.name
    created = c.create_processor(
        parent=parent,
        processor=documentai.Processor(display_name=PROCESSOR_NAME, type_="OCR_PROCESSOR"),
    )
    return created.name


def text_of(document: documentai.Document, anchor: documentai.Document.TextAnchor) -> str:
    return "".join(
        document.text[int(seg.start_index) : int(seg.end_index)] for seg in anchor.text_segments
    )


def ocr_page(c, processor: str, pdf: bytes) -> dict:
    result = c.process_document(
        request=documentai.ProcessRequest(
            name=processor,
            raw_document=documentai.RawDocument(content=pdf, mime_type="application/pdf"),
            process_options=documentai.ProcessOptions(
                ocr_config=documentai.OcrConfig(
                    enable_image_quality_scores=True,
                    premium_features=documentai.OcrConfig.PremiumFeatures(
                        compute_style_info=False, enable_math_ocr=False
                    ),
                )
            ),
        )
    )
    document = result.document
    page = document.pages[0]
    tokens = []
    for token in page.tokens:
        box = token.layout.bounding_poly.normalized_vertices
        tokens.append(
            {
                "text": text_of(document, token.layout.text_anchor).strip(),
                "x": round(sum(v.x for v in box) / len(box), 5),
                "y": round(sum(v.y for v in box) / len(box), 5),
                "confidence": round(token.layout.confidence, 4),
            }
        )
    quality = page.image_quality_scores.quality_score if page.image_quality_scores else None
    return {
        "text": document.text,
        "tokens": [t for t in tokens if t["text"]],
        "dimension": {"width": page.dimension.width, "height": page.dimension.height},
        "detected_languages": [lang.language_code for lang in page.detected_languages],
        "image_quality": quality,
        "tables_found": len(page.tables),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("doc", choices=["AAPSI", "APMT"])
    parser.add_argument("pages", help="1-based: 2, 2-5, 2,4 or all")
    args = parser.parse_args()

    settings = load_settings()
    c = client()
    processor = ensure_processor(c, settings.gcp_project_id)
    path = pdf_path(args.year, args.doc)
    RESULTS.mkdir(parents=True, exist_ok=True)
    for page in parse_pages(args.pages, len(PdfReader(path).pages)):
        result = ocr_page(c, processor, page_pdf(path, page))
        result |= {"year": args.year, "doc": args.doc, "page": page}
        out = RESULTS / f"{args.year}_{args.doc}_p{page:02d}.json"
        out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{out.name}: {len(result['tokens'])} tokens, quality {result['image_quality']}")


if __name__ == "__main__":
    main()
