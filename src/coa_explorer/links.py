"""Link each Part III reference to its Originating Observation in Part II, and report the result.

Every block of Part III rows names an earlier Audit Observation. When that observation lies in the
2020-2024 collection the block is `linked` to it; when it predates the collection it is
`out_of_collection` (still shown, cited to the AAR that tracks it); anything else is `unmatched`
and reported with the reason. Nothing is dropped and no match is guessed.

A link also compares the pages COA cites in Part III with the pages derived for Part II
(ADR-0001), so the drift of derived page numbers is measured rather than assumed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

LINKED = "linked"
OUT_OF_COLLECTION = "out_of_collection"
UNMATCHED = "unmatched"


@dataclass(frozen=True)
class Link:
    tracked_in: int  # the AAR whose Part III names the observation
    reference: str  # as printed in Part III
    origin_year: int | None
    origin_observation: int | None
    outcome: str  # linked | out_of_collection | unmatched (not a Status of Implementation)
    reason: str | None  # why it is unmatched or out of the collection
    origin_citation: str | None  # the Part II Citation, when linked
    cited_pages: tuple[int, int] | None  # pages COA cites in Part III
    derived_pages: tuple[int, int] | None  # pages derived for the Part II observation (ADR-0001)

    @property
    def drift(self) -> int | None:
        """Derived minus cited starting page; None unless linked with a cited page.

        Only the starting page is compared: from CY 2022 COA cites a single page ("Page 74") for
        an observation that Part II spreads over several.
        """
        if self.cited_pages is None or self.derived_pages is None:
            return None
        return self.derived_pages[0] - self.cited_pages[0]


def build_links(part2: Mapping[int, dict], part3: Mapping[int, dict]) -> list[Link]:
    """One Link per tracked observation of every Part III, in AAR and table order.

    `part2` and `part3` are the extracted records (as `to_dict` writes them) keyed by AAR year.
    """
    observations = {
        (year, o["number"]): o for year, record in part2.items() for o in record["observations"]
    }
    first_year = min(part2, default=None)
    links = []
    for tracked_in in sorted(part3):
        for tracked in part3[tracked_in]["observations"]:
            links.append(_link(tracked_in, tracked, observations, part2, first_year))
    return links


def _link(
    tracked_in: int,
    tracked: dict,
    observations: Mapping[tuple[int, int], dict],
    part2: Mapping[int, dict],
    first_year: int | None,
) -> Link:
    year, number = tracked["origin_year"], tracked["origin_observation"]
    start, end = tracked["origin_page_start"], tracked["origin_page_end"]
    cited = (start, end if end is not None else start) if start is not None else None

    def link(outcome: str, reason: str | None = None, observation: dict | None = None) -> Link:
        return Link(
            tracked_in=tracked_in,
            reference=tracked["reference"],
            origin_year=year,
            origin_observation=number,
            outcome=outcome,
            reason=reason,
            origin_citation=observation["citation"] if observation else None,
            cited_pages=cited,
            derived_pages=(
                (observation["page_start"], observation["page_end"]) if observation else None
            ),
        )

    if year is None or number is None:
        return link(UNMATCHED, "the reference does not give an AAR year and observation number")
    if year >= tracked_in:
        return link(UNMATCHED, f"CY {year} is not before the CY {tracked_in} AAR that cites it")
    if first_year is not None and year < first_year:
        return link(OUT_OF_COLLECTION, f"the CY {year} AAR is not in the {first_year}-2024 set")
    if year not in part2:
        return link(UNMATCHED, f"no Part II records for CY {year}")
    observation = observations.get((year, number))
    if observation is None:
        return link(UNMATCHED, f"CY {year} Part II has no Audit Observation No. {number}")
    return link(LINKED, observation=observation)


def report(links: list[Link]) -> dict:
    """The link report: counts, every unmatched reference, and the observed page drift."""
    by_outcome = {
        s: [link for link in links if link.outcome == s]
        for s in (LINKED, OUT_OF_COLLECTION, UNMATCHED)
    }
    return {
        "counts": {outcome: len(items) for outcome, items in by_outcome.items()},
        "unmatched": [_without_pages(link) for link in by_outcome[UNMATCHED]],
        "page_drift": [
            {
                "tracked_in": link.tracked_in,
                "origin": f"CY {link.origin_year} Observation No. {link.origin_observation}",
                "cited_pages": list(link.cited_pages),
                "derived_pages": list(link.derived_pages),
                "drift": link.drift,
            }
            for link in by_outcome[LINKED]
            if link.drift is not None
        ],
    }


def _without_pages(link: Link) -> dict:
    return {k: v for k, v in asdict(link).items() if k not in ("cited_pages", "derived_pages")}
