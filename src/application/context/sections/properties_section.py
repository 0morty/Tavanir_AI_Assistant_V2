from src.application.context.sections.prompt_section import PromptSection
from src.domain.context.summarizer import Summarizer
from src.domain.entities import ReferenceDetails
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class PropertiesSection(PromptSection):
    """The properties actually available in a ``ReferenceDetails`` instance.

    Renders the ``ReferenceDetails.properties`` as a markdown table with
    exactly the columns ``property name | type``. Only the properties available
    for the current Reference are listed, so the LLM never learns about
    properties whose value is unavailable. Empty details render as an empty
    string, and the section is then skipped by the ``PromptBuilder``.
    """

    def __init__(
        self,
        details: ReferenceDetails,
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        super().__init__(
            importance=importance,
            demand=demand,
            default_importance=0.5,
            default_demand=0.5,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
        )
        self._details = details

    @property
    def section_type(self) -> str:
        return "PROPERTIES"

    def body(self) -> str:
        if not self._details.properties:
            return ""
        lines = ["| property name | type |", "|---------------|------|"]
        lines.extend(
            f"| {name} | {property_type} |"
            for name, property_type in self._details.properties
        )
        return "\n".join(lines)