from src.domain.entities import Chunk
from src.application.context.section import Section


class ChunksSection(Section):
    """Retrieval (RAG) context chunks."""

    def __init__(
        self,
        chunks: list[Chunk],
        *,
        importance: float | None = None,
        demand: float | None = None,
    ) -> None:
        super().__init__(
            separator="\n\n",
            importance=importance,
            demand=demand,
            default_importance=0.4,
            default_demand=0.5,
        )
        self._chunks = chunks

    @property
    def section_type(self) -> str:
        return "CHUNKS"

    @property
    def pre_context(self) -> str:
        return "Relevant context chunks:"

    def body(self) -> str:
        rendered = [
            f"Chunk {i}:\n{chunk.content}" for i, chunk in enumerate(self._chunks, 1)
        ]
        return self.separator.join(rendered)