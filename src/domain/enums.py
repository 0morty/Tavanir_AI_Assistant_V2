from enum import Enum

from src.domain.exceptions import InvalidSuggestionStatusError


class HistoryRole(Enum):
    """Sender role of a history message, OpenAI-compatible for chat history."""

    USER = "user"
    SYSTEM = "system"
    ASSISTANT = "assistant"


class SuggestionStatus(Enum):
    NOT_ACCEPTED = ("عدم پذیرش", 1)
    REJECTED = ("رد", 2)
    APPROVED = ("مصوب", 3)
    PENDING = ("در حال اجرا", 4)
    EXECUTED = ("اجرا شده", 5)

    def __init__(self, title_fa: str, status_id: int):
        self.title_fa = title_fa
        self.status_id = status_id

    @classmethod
    def from_string(cls, value: str) -> "SuggestionStatus":
        """Find status by Persian title."""
        for item in cls:
            if item.title_fa == value or item.name == value:
                return item
        raise InvalidSuggestionStatusError(
            f"Unknown suggestion status string: '{value}'"
        )

    @classmethod
    def from_id(cls, status_id: int) -> "SuggestionStatus":
        """Find status by status_id integer."""
        for item in cls:
            if item.status_id == status_id:
                return item
        raise InvalidSuggestionStatusError(f"Unknown suggestion status ID: {status_id}")
