from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from src.domain.entities import ReferenceDetails

if TYPE_CHECKING:  # pragma: no cover
    from src.application.reference.template_validator import TemplateValidationResult


class ITemplateValidator(ABC):
    """Port for validating a reference template against a :class:`ReferenceDetails`."""

    @abstractmethod
    def validate(
        self,
        template: str,
        details: ReferenceDetails,
    ) -> "TemplateValidationResult":
        """Return the validation outcome for ``template``."""