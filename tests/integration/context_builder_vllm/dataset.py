"""Deterministic English evidence already retrieved from an artificial utility."""
from dataclasses import dataclass

from src.domain.entities import GenerationChunk, HistoryMessage, Reference
from src.domain.enums import HistoryRole

ROLE = "You are an engineering decision-support analyst for the fictional Northbridge utility."
SYSTEM = ("Use only the supplied evidence. Separate observations from recommendations. "
          "State uncertainty and cite chunk identifiers. Never present advice as an approved decision.")
USER = "Which maintenance changes should Northbridge pilot first? Answer in at most two sentences."
OUTPUT = "Return a concise English analysis with evidence identifiers and one uncertainty."

FACTS = {
    "A": "Relay calibration at Cedar substation reduced nuisance trips from twelve to three per quarter.",
    "B": "Dispatch scheduling at River depot reduced median crew arrival time from 48 to 31 minutes.",
    "C": "Meter audits in Harbor district found incorrect multipliers on seven of 240 sampled meters.",
    "D": "Cable thermal inspections at Hill feeder found four joints requiring planned replacement.",
    "E": "Battery tests at Lake control room found reserve capacity below the 90 minute design target.",
}


@dataclass(frozen=True)
class EvidenceReference(Reference):
    title: str
    article: int

    @property
    def description(self) -> str:
        return "An artificial Northbridge maintenance bulletin used as already-retrieved evidence."


def chunks() -> list[GenerationChunk]:
    result = []
    for index, (label, fact) in enumerate(FACTS.items(), start=1):
        paragraphs = [f"Evidence {label}. {fact}"]
        for cycle in range(1, 5):
            paragraphs.append(
                f"Inspection cycle {cycle} for evidence {label}: engineers recorded equipment condition, "
                "weather and planned outage duration before applying the intervention. The maintenance "
                "supervisor reviewed the readings against the previous inspection and retained the raw "
                "measurements in the local register. These observations describe a limited pilot, so "
                "seasonal demand, staffing differences and equipment age may affect a wider rollout. "
                "A follow-up assessment must compare service continuity and total maintenance hours."
            )
        result.append(GenerationChunk(f"chunk-{label}", "\n\n".join(paragraphs),
                                      EvidenceReference(f"Northbridge bulletin {label}", index)))
    return result


def history() -> list[HistoryMessage]:
    return [HistoryMessage(HistoryRole.USER if index % 2 == 0 else HistoryRole.ASSISTANT,
                           f"Turn {index + 1}: " +
                           ("Please preserve the distinction between observed results and proposed work. "
                            if index % 2 == 0 else
                            "The evidence is preliminary; a controlled pilot should measure reliability and cost. ") * 4)
            for index in range(8)]
