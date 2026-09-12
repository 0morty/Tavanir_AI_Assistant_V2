from src.domain.entities import Chunk
from src.application.prompt_architecture.prompt_section import PromptSection


class ChunksSection(PromptSection):
    """Retrieval (RAG) context chunks."""

    def __init__(self, chunks: list[Chunk]) -> None:
        super().__init__(separator="\n\n")
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