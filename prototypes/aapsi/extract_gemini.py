"""Ask Gemini to read AAPSI pages straight from the scanned PDF into the known column schema.

    uv run --group prototype python -m prototypes.aapsi.extract_gemini 2023 AAPSI 2 --model MODEL
    uv run --group prototype python -m prototypes.aapsi.extract_gemini 2024 AAPSI 2-25

One request per page, so a failure costs one page and the cost per page is measured directly.
Writes prototypes/aapsi/results/gemini/<year>_<doc>_p<page>_<model>.json (rows plus token usage).
"""

from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

from google import genai
from google.genai import types
from pypdf import PdfReader, PdfWriter

from coa_explorer.config import REPO_ROOT, load_settings
from prototypes.aapsi.compare import FIELDS

RESULTS = Path(__file__).parent / "results" / "gemini"

PROMPT = """\
This is one scanned page of the City of Manila's Agency Action Plan and Status of Implementation
(AAPSI), a landscape table. Transcribe the table rows exactly as printed.

Columns, left to right: Reference; Audit Observations; Audit Recommendations; Agency Action Plan
(sub-columns Action Plan, Person/Dept. Responsible, Target Implementation Date From, To); Status of
Implementation; Reason for Partial/Delay/Non-Implementation, if applicable; Action Taken/Action to
be Taken.

Rules:
- One output row per horizontal band of the Audit Observations / Audit Recommendations columns.
  A band is closed off by the ruled lines in those columns.
- A cell on the right that is merged across several bands belongs to the first band it covers; leave
  it empty on the others. Never repeat text to fill a merged cell.
- A cell that is blank in the scan is an empty string. Do not infer or fill anything in.
- Copy text character for character, including numbers, peso amounts, item numbers such as
  "1.7.1" or "2.19", sub-item letters, and bullet items. Keep the scan's own wording even if it
  looks like a typo. Join words broken across lines; do not add line breaks inside a cell.
- Ignore the page title, the page number and anything outside the table (letters, signatures,
  stamps, footnotes).
"""


def row_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {f: {"type": "string"} for f in FIELDS},
                    "required": list(FIELDS),
                },
            }
        },
        "required": ["rows"],
    }


def pdf_path(year: int, doc: str) -> Path:
    folder = REPO_ROOT / "coa-audit-reports" / f"Manila-City-Annual-Audit-Report-{year}"
    return folder / "AAPSI_APMT" / f"ManilaCity{year}_{doc}.pdf"


def page_pdf(path: Path, page: int) -> bytes:
    """One page as its own PDF, sent as the scan is, rotation flag and all."""
    writer = PdfWriter()
    writer.add_page(PdfReader(path).pages[page - 1])
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def parse_pages(spec: str, last: int) -> list[int]:
    if spec == "all":
        return list(range(1, last + 1))
    pages = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        pages += range(int(lo), int(hi or lo) + 1)
    return pages


def extract_page(client, model: str, pdf: bytes, resolution: str, thinking: str | None) -> dict:
    started = time.monotonic()
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=pdf, mime_type="application/pdf"), PROMPT],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=row_schema(),
            media_resolution=resolution,
            max_output_tokens=32768,
            thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
        ),
    )
    usage = response.usage_metadata
    return {
        "seconds": round(time.monotonic() - started, 1),
        "finish_reason": str(response.candidates[0].finish_reason) if response.candidates else None,
        "usage": {
            "prompt_tokens": usage.prompt_token_count,
            "output_tokens": usage.candidates_token_count,
            "thought_tokens": usage.thoughts_token_count or 0,
        },
        "rows": json.loads(response.text)["rows"] if response.text else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("year", type=int)
    parser.add_argument("doc", choices=["AAPSI"], help="APMT has a different column layout")
    parser.add_argument("pages", help="1-based: 2, 2-5, 2,4 or all")
    parser.add_argument("--model", default=None, help="default: GEMINI_ANSWER_MODEL")
    parser.add_argument("--resolution", default="MEDIA_RESOLUTION_HIGH")
    parser.add_argument("--thinking", default=None, help="thinking level, e.g. LOW or MINIMAL")
    args = parser.parse_args()

    settings = load_settings()
    model = args.model or settings.gemini_answer_model
    client = genai.Client(
        vertexai=True,
        project=settings.gcp_project_id,
        location=settings.gemini_location,
        http_options=types.HttpOptions(timeout=300_000),
    )
    path = pdf_path(args.year, args.doc)
    RESULTS.mkdir(parents=True, exist_ok=True)
    for page in parse_pages(args.pages, len(PdfReader(path).pages)):
        result = extract_page(client, model, page_pdf(path, page), args.resolution, args.thinking)
        result |= {"year": args.year, "doc": args.doc, "page": page, "model": model}
        suffix = f"_think-{args.thinking.lower()}" if args.thinking else ""
        out = RESULTS / f"{args.year}_{args.doc}_p{page:02d}_{model}{suffix}.json"
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{out.name}: {len(result['rows'])} rows, {result['usage']}, {result['seconds']}s")


if __name__ == "__main__":
    main()
