from typing import Any

from src.application.context.sections.referenced_collection_section import (
    ReferencedCollectionSection,
)
from src.application.interfaces.i_text_summarizer import ITextSummarizer
from src.domain.context.overflow.truncate import TruncateStrategy
from src.domain.context.summarizer import Summarizer
from src.domain.context.tokenizer import Tokenizer
from src.domain.entities import HistoryMessage
from src.domain.overflow_strategy_stack import OverflowStrategyStack


class HistorySection(ReferencedCollectionSection):
    """Conversation turns with structured fitted messages for chat serialization."""

    def __init__(
        self,
        messages: list[HistoryMessage],
        *,
        importance: float | None = None,
        demand: float | None = None,
        overflow_strategies: OverflowStrategyStack | None = None,
        summarizer: Summarizer | None = None,
        chunk_summarizer: ITextSummarizer | None = None,
    ) -> None:
        super().__init__(
            items=messages,
            separator="\n\n",
            importance=importance,
            demand=demand,
            default_importance=0.3,
            default_demand=0.4,
            overflow_strategies=overflow_strategies,
            summarizer=summarizer,
            chunk_summarizer=chunk_summarizer,
        )
        self._fitted_messages: tuple[HistoryMessage, ...] = ()

    @property
    def fitted_messages(self) -> tuple[HistoryMessage, ...]:
        """Turns produced by the last render or overflow operation."""
        return self._fitted_messages

    def render(self) -> str:
        content = super().render()
        self._fitted_messages = tuple(self._items) if content else ()
        return content

    def _set_fitted_messages(self, messages: list[HistoryMessage]) -> str:
        self._fitted_messages = tuple(messages)
        return self.item_separator.join(self.item_content(item) for item in messages)

    def truncate(
        self, content: str, capacity_tokens: int, *, tokenizer: Tokenizer
    ) -> str:
        """Fit whole turns, then shorten at most one turn's content in place."""
        if not self._items or capacity_tokens <= 0:
            return self._set_fitted_messages([])

        fitted: list[HistoryMessage] = []
        parts: list[str] = []
        for item in self._items:
            rendered = self.item_content(item)
            separator = self.item_separator if parts else ""
            previous = self.item_separator.join(parts)
            if tokenizer.count_tokens(previous + separator + rendered) <= capacity_tokens:
                fitted.append(item)
                parts.append(rendered)
                continue

            role_prefix = f"{item.role.value}: "
            leading = previous + separator + role_prefix
            if tokenizer.count_tokens(leading) > capacity_tokens:
                break
            remaining = capacity_tokens - tokenizer.count_tokens(leading)
            shortened = TruncateStrategy(tokenizer).apply(item.content, remaining)
            candidate = HistoryMessage(role=item.role, content=shortened)

            # Count the actual joined text; token counts need not be additive.
            while tokenizer.count_tokens(
                previous + separator + self.item_content(candidate)
            ) > capacity_tokens:
                if not candidate.content:
                    break
                candidate = HistoryMessage(
                    role=item.role, content=candidate.content[:-1]
                )
            if tokenizer.count_tokens(
                previous + separator + self.item_content(candidate)
            ) <= capacity_tokens:
                fitted.append(candidate)
            break

        return self._set_fitted_messages(fitted)

    def ignore(
        self, content: str, capacity_tokens: int, *, tokenizer: Tokenizer
    ) -> str:
        """Keep complete turns in order while their rendered text fits."""
        if not self._items or capacity_tokens <= 0:
            return self._set_fitted_messages([])

        fitted: list[HistoryMessage] = []
        used_tokens = 0
        separator_tokens = tokenizer.count_tokens(self.item_separator)
        for item in self._items:
            rendered = self.item_content(item)
            cost = tokenizer.count_tokens(rendered)
            if fitted:
                cost += separator_tokens
            if used_tokens + cost > capacity_tokens:
                break
            fitted.append(item)
            used_tokens += cost
        return self._set_fitted_messages(fitted)

    def summarize(self, content: str, capacity_tokens: int) -> str | None:
        """Use the collection batch mapping, then retain each turn's role."""
        result = super().summarize(content, capacity_tokens)
        if result is None:
            return None
        return self._set_fitted_messages(list(self.summarized_items or ()))

    @property
    def section_type(self) -> str:
        return "HISTORY"

    @property
    def pre_context(self) -> str:
        return "History of previous interactions:"

    def item_content(self, item: Any) -> str:
        """Render a turn as role: content so the sender is preserved."""
        return f"{item.role.value}: {item.content}"
