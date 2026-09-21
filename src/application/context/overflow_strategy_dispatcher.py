from src.application.interfaces.i_compressible_section import CompressibleSection
from src.domain.context.tokenizer import Tokenizer
from src.domain.enums import OverflowStrategy


class OverflowStrategyDispatcher:
    """Dispatch an ``OverflowStrategy`` to the matching :class:`CompressibleSection` operation.

    The dispatcher owns the mapping only -- it selects the operation and
    invokes it, but never implements the reduction itself (that lives in the
    Section). ``ContextBuilder`` therefore contains no strategy-specific
    branching: it requests an operation through this class.

    Mapping:

    ``SUMMARIZE`` -> section.summarize(...)
    ``TRUNCATE``  -> section.truncate(...)
    ``IGNORE``    -> section.ignore(...)
    """

    def apply(
        self,
        section: CompressibleSection,
        strategy: OverflowStrategy,
        content: str,
        capacity_tokens: int,
        *,
        tokenizer: Tokenizer,
    ) -> str | None:
        """Invoke the operation for ``strategy`` on ``section``.

        Returns the reduced content as a ``str``, or ``None`` when the strategy
        is not applicable for this Section (e.g. a Section without a configured
        summarizer returns ``None`` from ``summarize``), so the caller can fall
        through to the next strategy in the Section's overflow stack.
        """
        if strategy is OverflowStrategy.SUMMARIZE:
            return section.summarize(content, capacity_tokens)
        if strategy is OverflowStrategy.TRUNCATE:
            return section.truncate(content, capacity_tokens, tokenizer=tokenizer)
        if strategy is OverflowStrategy.IGNORE:
            return section.ignore(content, capacity_tokens, tokenizer=tokenizer)
        raise ValueError(f"Unsupported overflow strategy {strategy!r}.")