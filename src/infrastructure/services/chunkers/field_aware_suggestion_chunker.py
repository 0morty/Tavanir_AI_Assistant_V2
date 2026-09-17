import uuid
from collections.abc import Sequence
from typing import TypeGuard

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.domain.entities import (
    NOISE_PLACEHOLDERS,
    Chunk,
    Suggestion,
    SuggestionChunk,
    SuggestionChunkMetadata,
)
from src.domain.enums import ChunkStatus, SuggestionChunkType
from src.domain.exceptions import SuggestionChunkingError
from src.domain.interfaces.i_chunking_strategy import (
    IChunkingStrategy,
)


class FieldAwareSuggestionChunker(
    IChunkingStrategy[Suggestion, SuggestionChunkMetadata]
):
    """
    Production-grade field-aware chunker for historical employee suggestions (ADR-002).

    Decomposes a Suggestion entity into up to 4 discrete child chunks (TITLE, PROBLEM,
    SOLUTION, EVALUATION) using strict field isolation, Persian sentence/paragraph
    boundary preservation for long essays via LangChain's RecursiveCharacterTextSplitter,
    and noise token filtering.
    """

    DEFAULT_SEPARATORS: list[str] = ["\n\n", "\n", "؛", ".", "!", "؟", " "]
    DEFAULT_NOISE_PLACEHOLDERS: frozenset[str] = NOISE_PLACEHOLDERS

    def __init__(
        self,
        max_chunk_chars: int = 1500,
        overlap_chars: int = 150,
        min_chunk_chars: int = 5,
        separators: Sequence[str] | None = None,
        noise_placeholders: frozenset[str] | None = None,
    ) -> None:
        self._max_chunk_chars = max_chunk_chars
        self._overlap_chars = overlap_chars
        self._min_chunk_chars = min_chunk_chars
        self._separators = (
            list(separators)
            if separators is not None
            else list(self.DEFAULT_SEPARATORS)
        )
        self._noise_placeholders = (
            noise_placeholders
            if noise_placeholders is not None
            else self.DEFAULT_NOISE_PLACEHOLDERS
        )
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._max_chunk_chars,
            chunk_overlap=self._overlap_chars,
            separators=self._separators,
            keep_separator=True,
            strip_whitespace=True,
        )

    def _is_valid_content(self, text: str | None) -> TypeGuard[str]:
        """Determines if a field has substantive semantic content worth embedding."""
        if not text:
            return False
        cleaned = text.strip()
        if len(cleaned) < self._min_chunk_chars:
            return False
        return cleaned not in self._noise_placeholders

    def _split_text(self, text: str) -> list[str]:
        """
        Recursively splits long Persian text along hierarchical boundaries
        using LangChain's RecursiveCharacterTextSplitter under max_chunk_chars
        with overlap_chars overlap.
        """
        text = text.strip()
        if len(text) <= self._max_chunk_chars:
            return [text]

        return self._text_splitter.split_text(text)

    async def chunk(self, document: Suggestion) -> list[SuggestionChunk]:
        """
        Decomposes a Suggestion into discrete child chunks (ADR-002).

        Args:
            document: Normalized Suggestion entity.

        Returns:
            List of SuggestionChunk instances ready for vector embedding.

        Raises:
            SuggestionChunkingError: If the suggestion lacks a valid title or ID.
        """
        if not document.id or not document.id.strip():
            raise SuggestionChunkingError("Suggestion must have a valid non-empty id.")

        if not self._is_valid_content(document.content.title):
            raise SuggestionChunkingError(
                "Suggestion must have a valid non-empty title."
            )

        if not self._is_valid_content(document.content.problem):
            raise SuggestionChunkingError(
                "Suggestion must have a valid non-empty problem."
            )

        if not self._is_valid_content(document.content.solution):
            raise SuggestionChunkingError(
                "Suggestion must have a valid non-empty solution."
            )

        chunks: list[SuggestionChunk] = []

        # 1. TITLE Chunk (Domain Anchoring: context_title + title)
        context_title = document.context_title
        if self._is_valid_content(context_title):
            title_content = f"حوزه: {context_title.strip()} | عنوان: {document.content.title.strip()}"
        else:
            title_content = document.content.title.strip()

        chunks.append(
            Chunk[SuggestionChunkMetadata](
                chunk_id=str(uuid.uuid4()),
                parent_id=document.id,
                content=title_content,
                metadata=SuggestionChunkMetadata(
                    chunk_type=SuggestionChunkType.TITLE,
                    sub_index=0,
                    status=document.evaluation.status,
                    context_title=document.context_title,
                    date=document.date,
                ),
                parent_content=None,
                chunk_status=ChunkStatus.ACTIVE,
            )
        )

        # 2. PROBLEM Chunk (Strict Field Isolation: pure defect text)
        problem_text = document.content.problem.strip()
        sub_texts = self._split_text(problem_text)
        for idx, sub_text in enumerate(sub_texts):
            chunks.append(
                Chunk[SuggestionChunkMetadata](
                    chunk_id=str(uuid.uuid4()),
                    parent_id=document.id,
                    content=sub_text,
                    metadata=SuggestionChunkMetadata(
                        chunk_type=SuggestionChunkType.PROBLEM,
                        sub_index=idx,
                        status=document.evaluation.status,
                        context_title=document.context_title,
                        date=document.date,
                    ),
                    parent_content=None,
                    chunk_status=ChunkStatus.ACTIVE,
                )
            )

        # 3. SOLUTION Chunk (Strict Field Isolation: pure engineering mechanism)
        solution_text = document.content.solution.strip()
        sub_texts = self._split_text(solution_text)
        for idx, sub_text in enumerate(sub_texts):
            chunks.append(
                Chunk[SuggestionChunkMetadata](
                    chunk_id=str(uuid.uuid4()),
                    parent_id=document.id,
                    content=sub_text,
                    metadata=SuggestionChunkMetadata(
                        chunk_type=SuggestionChunkType.SOLUTION,
                        sub_index=idx,
                        status=document.evaluation.status,
                        context_title=document.context_title,
                        date=document.date,
                    ),
                    parent_content=None,
                    chunk_status=ChunkStatus.ACTIVE,
                )
            )

        # 4. EVALUATION Chunk (Consolidation without empty lines)
        scrutiny = document.evaluation.scrutiny
        description = document.evaluation.description
        eval_parts: list[str] = []

        if self._is_valid_content(scrutiny):
            eval_parts.append(f"بررسی کمیته: {scrutiny.strip()}")

        if self._is_valid_content(description):
            eval_parts.append(f"توضیحات مصوبه: {description.strip()}")

        if eval_parts:
            eval_content = "\n".join(eval_parts)
            chunks.append(
                Chunk[SuggestionChunkMetadata](
                    chunk_id=str(uuid.uuid4()),
                    parent_id=document.id,
                    content=eval_content,
                    metadata=SuggestionChunkMetadata(
                        chunk_type=SuggestionChunkType.EVALUATION,
                        sub_index=0,
                        status=document.evaluation.status,
                        context_title=document.context_title,
                        date=document.date,
                    ),
                    parent_content=None,
                    chunk_status=ChunkStatus.ACTIVE,
                )
            )

        return chunks


__all__ = ["FieldAwareSuggestionChunker"]
