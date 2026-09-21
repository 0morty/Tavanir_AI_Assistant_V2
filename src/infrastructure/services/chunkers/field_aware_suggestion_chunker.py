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
from src.domain.enums import (
    ChunkStatus,
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionChunkType,
)
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

    def _is_substantive_commentary(
        self, text: str | None, min_len: int = 15
    ) -> TypeGuard[str]:
        """Determines if an evaluation comment contains substantive human reasoning worth embedding."""
        if not text:
            return False
        cleaned = text.strip()
        if len(cleaned) < min_len:
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

        # Extract parent suggestion scrutiny metadata for chunk-level filter inheritance
        committee_scrutiny = document.evaluation.scrutiny
        committee_scrutiny_id = (
            committee_scrutiny.code
            if committee_scrutiny
            else document.evaluation.scrutiny_id
        )
        secretariat_scrutiny = (
            document.secretariat_evaluation.scrutiny
            if document.secretariat_evaluation
            else None
        )
        secretariat_scrutiny_id = (
            secretariat_scrutiny.code
            if secretariat_scrutiny
            else (
                document.secretariat_evaluation.scrutiny_id
                if document.secretariat_evaluation
                else None
            )
        )

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
                    committee_scrutiny=committee_scrutiny,
                    committee_scrutiny_id=committee_scrutiny_id,
                    secretariat_scrutiny=secretariat_scrutiny,
                    secretariat_scrutiny_id=secretariat_scrutiny_id,
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
                        committee_scrutiny=committee_scrutiny,
                        committee_scrutiny_id=committee_scrutiny_id,
                        secretariat_scrutiny=secretariat_scrutiny,
                        secretariat_scrutiny_id=secretariat_scrutiny_id,
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
                        committee_scrutiny=committee_scrutiny,
                        committee_scrutiny_id=committee_scrutiny_id,
                        secretariat_scrutiny=secretariat_scrutiny,
                        secretariat_scrutiny_id=secretariat_scrutiny_id,
                    ),
                    parent_content=None,
                    chunk_status=ChunkStatus.ACTIVE,
                )
            )

        # 4. EVALUATION Chunk (Substantive Commentary Guard)
        # An EVALUATION chunk is ONLY emitted if either Committee description or
        # Secretariat comment contains substantive human commentary (>= 15 chars, not in noise placeholders).
        has_substantive_description = self._is_substantive_commentary(
            document.evaluation.description, min_len=15
        )
        has_substantive_sec_comment = False
        if document.secretariat_evaluation and document.secretariat_evaluation.comment:
            has_substantive_sec_comment = self._is_substantive_commentary(
                document.secretariat_evaluation.comment, min_len=15
            )

        if has_substantive_description or has_substantive_sec_comment:
            eval_parts: list[str] = []

            # 4a. Secretariat evaluation block (if substantive comment exists)
            if has_substantive_sec_comment and document.secretariat_evaluation:
                sec = document.secretariat_evaluation
                sec_title = sec.scrutiny.title_fa if sec.scrutiny else ""
                if self._is_valid_content(sec_title):
                    eval_parts.append(f"ارزیابی دبیرخانه: {sec_title}")
                if self._is_valid_content(sec.comment):
                    eval_parts.append(f"نظر دبیرخانه: {sec.comment.strip()}")

            # 4b. Committee evaluation block (if substantive description exists)
            if has_substantive_description:
                com = document.evaluation
                com_title = com.scrutiny.title_fa if com.scrutiny else ""
                if self._is_valid_content(com_title):
                    eval_parts.append(f"بررسی کمیته: {com_title}")
                if self._is_valid_content(com.description):
                    eval_parts.append(f"توضیحات مصوبه: {com.description.strip()}")

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
                            committee_scrutiny=committee_scrutiny,
                            committee_scrutiny_id=committee_scrutiny_id,
                            secretariat_scrutiny=secretariat_scrutiny,
                            secretariat_scrutiny_id=secretariat_scrutiny_id,
                        ),
                        parent_content=None,
                        chunk_status=ChunkStatus.ACTIVE,
                    )
                )

        return chunks


__all__ = ["FieldAwareSuggestionChunker"]
