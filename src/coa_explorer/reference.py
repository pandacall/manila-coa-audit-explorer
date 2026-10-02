"""The reference set: questions with known-good answers, for the evaluation harness.

Each item says what a good answer cites and states, or that the app should refuse. The owner
approves items one by one; only approved items are scored.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from coa_explorer.citation import parse_citation

QuestionType = Literal["observation", "follow_up", "financial"]
Language = Literal["en", "fil", "taglish"]


class ReferenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    language: Language
    question_type: QuestionType
    expected_citations: list[str] = Field(
        default_factory=list, description="Citations in COA's format that a good answer cites"
    )
    key_facts: list[str] = Field(
        default_factory=list, description="Facts a good answer must state, one short sentence each"
    )
    unanswerable: bool = Field(description="True when the AARs don't cover it: the app must refuse")
    approved: bool = Field(description="True once the owner has approved the item; else unscored")

    @field_validator("expected_citations")
    @classmethod
    def citations_are_in_coas_format(cls, citations: list[str]) -> list[str]:
        for citation in citations:
            parse_citation(citation)
        return citations

    @model_validator(mode="after")
    def answerable_items_say_what_a_good_answer_holds(self) -> ReferenceItem:
        if self.unanswerable and (self.expected_citations or self.key_facts):
            raise ValueError("an unanswerable item has no expected Citations or key facts")
        if not self.unanswerable and not (self.expected_citations and self.key_facts):
            raise ValueError("an answerable item needs expected Citations and key facts")
        return self


class ReferenceFileError(ValueError):
    """The reference file is unreadable or has an invalid item."""


def load_reference(path: Path) -> list[ReferenceItem]:
    """All items of a reference file, `{"items": [...]}`, approved or not."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        records = raw["items"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReferenceFileError(
            f'{path}: cannot read a {{"items": [...]}} file ({error})'
        ) from error
    items: list[ReferenceItem] = []
    for position, record in enumerate(records, start=1):
        label = record.get("id", f"#{position}") if isinstance(record, dict) else f"#{position}"
        try:
            items.append(ReferenceItem.model_validate(record))
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'item'}: {e['msg']}"
                for e in error.errors()
            )
            raise ReferenceFileError(f"{path}: item {label}: {problems}") from error
    ids = [item.id for item in items]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ReferenceFileError(f"{path}: duplicate item id(s): {', '.join(duplicates)}")
    return items
