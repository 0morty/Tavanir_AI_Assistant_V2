from abc import ABC, abstractmethod

from src.domain.entities import Reference


class IReferenceGenerator(ABC):
    """Port for generating a human-readable representation of a Reference.

    This is the external fallback used when a Reference provides no native
    ``fluent_text()`` rendering. Implementations must not depend on concrete
    Section types and must operate exclusively on the Reference abstraction.
    """

    @abstractmethod
    def generate(self, reference: Reference) -> str:
        """Return the human-readable Reference text, or an empty string when
        the Reference provides no renderable information."""