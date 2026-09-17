from collections.abc import Mapping

from src.application.interfaces.i_reference_generator import IReferenceGenerator
from src.domain.entities import Reference

_DEFAULT_PHRASES: dict[str, str] = {
    "page": "on page {value}",
    "article": "Article {value}",
    "chapter": "chapter '{value}'",
    "section": "in section '{value}'",
    "title": "from '{value}'",
    "document": "from '{value}'",
    "document_title": "from '{value}'",
    "author": "written by {value}",
    "url": "at {value}",
    "domain": "on {value}",
    "date": "dated {value}",
}


class DeterministicReferenceGenerator(IReferenceGenerator):
    """Simplified, deterministic Reference generator without an LLM.

    Produces a human-readable representation from the currently available
    properties of a Reference. Common property names map to natural-language
    phrases; unknown properties fall back to ``name: value``. Property order
    follows ``ReferenceDetails`` (alphabetical), keeping output deterministic.

    This is a temporary stand-in until the LLM-based generator, which needs
    ContextBuilder, is implemented.
    """

    def __init__(self, phrases: Mapping[str, str] | None = None) -> None:
        self._phrases = dict(_DEFAULT_PHRASES if phrases is None else phrases)

    def generate(self, reference: Reference) -> str:
        phrases = [
            self._phrase_for(name, getattr(reference, name))
            for name, _ in reference.details.properties
        ]
        if not phrases:
            return ""
        return f"{', '.join(phrases)}, it is stated:"

    def _phrase_for(self, name: str, value: object) -> str:
        template = self._phrases.get(name)
        if template is None:
            return f"{name}: {value}"
        return template.format(value=value)