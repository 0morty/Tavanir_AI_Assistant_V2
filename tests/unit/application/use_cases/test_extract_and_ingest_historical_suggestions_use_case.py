from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence

import pytest
from src.application.interfaces.i_checkpoint_repository import ICheckpointRepository
from src.application.interfaces.i_dense_embedder import IDenseEmbedder
from src.application.interfaces.i_historical_suggestion_extractor import (
    IHistoricalSuggestionExtractor,
)
from src.application.interfaces.i_skipped_suggestion_repository import (
    ISkippedSuggestionRepository,
)
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.application.interfaces.i_text_normalizer import ITextNormalizer
from src.application.services.hybrid_embedding_service import HybridEmbeddingService
from src.application.use_cases.extract_and_ingest_historical_suggestions_use_case import (
    ExtractAndIngestHistoricalSuggestionsUseCase,
    _resolve_committee_scrutiny,
    _resolve_secretariat_scrutiny,
    _resolve_suggestion_status,
)

from src.application.dtos import (
    CheckpointData,
    RawSuggestionDataDTO,
    SkippedRecordDTO,
)
from src.application.interfaces import IUnitOfWork
from src.domain.entities import (
    Chunk,
    SparseVector,
    Suggestion,
    SuggestionChunkMetadata,
)
from src.domain.enums import (
    CommitteeScrutiny,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidCommitteeScrutinyError,
    InvalidSecretariatScrutinyError,
    InvalidSuggestionStatusError,
    VectorStorageError,
)
from src.domain.interfaces import (
    ISuggestionChunker,
    ISuggestionRepository,
    ISuggestionVectorRepository,
)


class FakeSuggestionRepo(ISuggestionRepository):
    def __init__(self):
        self.saved_suggestions: list[Suggestion] = []
        self.deleted_ids: list[str] = []

    async def get_by_id(
        self, suggestion_id: str, include_deleted: bool = False
    ) -> Suggestion | None:
        for s in self.saved_suggestions:
            if s.id == suggestion_id:
                if not include_deleted and s.is_deleted:
                    continue
                return s
        return None

    async def get_by_ids(
        self, suggestion_ids: Sequence[str], include_deleted: bool = False
    ) -> list[Suggestion]:
        results = []
        for s in self.saved_suggestions:
            if s.id in suggestion_ids:
                if not include_deleted and s.is_deleted:
                    continue
                results.append(s)
        return results

    async def save(self, suggestion: Suggestion) -> None:
        self.saved_suggestions.append(suggestion)

    async def save_batch(self, suggestions: Sequence[Suggestion]) -> None:
        self.saved_suggestions.extend(suggestions)

    async def delete(self, suggestion_id: str) -> None:
        self.deleted_ids.append(suggestion_id)
        self.saved_suggestions = [
            s for s in self.saved_suggestions if s.id != suggestion_id
        ]

    async def delete_batch(self, suggestion_ids: Sequence[str]) -> None:
        self.deleted_ids.extend(suggestion_ids)
        self.saved_suggestions = [
            s for s in self.saved_suggestions if s.id not in suggestion_ids
        ]

    async def soft_delete(self, suggestion_id: str) -> None:
        for s in self.saved_suggestions:
            if s.id == suggestion_id:
                s.mark_deleted()


class FakeCheckpointRepo(ICheckpointRepository):
    def __init__(self, initial_checkpoint: CheckpointData | None = None):
        self.checkpoint: CheckpointData | None = initial_checkpoint
        self.saved_checkpoints: list[tuple[str, int, str | None, int]] = []
        self.cleared = False

    @property
    def watermark(self) -> str | int | None:
        return self.checkpoint.last_processed_id if self.checkpoint else None

    async def get_checkpoint(self, job_name: str) -> CheckpointData | None:
        return self.checkpoint

    async def save_checkpoint(
        self, job_name: str, offset: int, last_id: str | None, total_processed: int
    ) -> None:
        self.checkpoint = CheckpointData(
            last_offset=offset,
            last_processed_id=last_id,
            total_processed=total_processed,
        )
        self.saved_checkpoints.append((job_name, offset, last_id, total_processed))

    async def clear_checkpoint(self, job_name: str) -> None:
        self.checkpoint = None
        self.cleared = True


class FakeSkippedRepo(ISkippedSuggestionRepository):
    def __init__(self):
        self.saved_records: list[SkippedRecordDTO] = []

    async def save_batch(self, skipped_records: Sequence[SkippedRecordDTO]) -> None:
        self.saved_records.extend(skipped_records)


class FakeUoW(IUnitOfWork):
    def __init__(
        self,
        suggestion_repo: FakeSuggestionRepo,
        checkpoint_repo: FakeCheckpointRepo,
        skipped_repo: FakeSkippedRepo,
    ):
        self._suggestions = suggestion_repo
        self._checkpoints = checkpoint_repo
        self._skipped = skipped_repo
        self.committed = False
        self.commit_count = 0

    @property
    def suggestions(self) -> ISuggestionRepository:
        return self._suggestions

    @property
    def checkpoints(self) -> ICheckpointRepository:
        return self._checkpoints

    @property
    def skipped_suggestions(self) -> ISkippedSuggestionRepository:
        return self._skipped

    async def try_acquire_advisory_lock(self, lock_key: int) -> bool:
        return True

    async def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    async def rollback(self) -> None:
        pass


class FakeExtractor(IHistoricalSuggestionExtractor):
    def __init__(self, batches: list[list[RawSuggestionDataDTO]]):
        self.batches = batches
        self.stream_calls: list[tuple[int, int]] = []

    async def stream_suggestions(
        self, batch_size: int, start_offset: int = 0
    ) -> AsyncGenerator[list[RawSuggestionDataDTO], None]:
        self.stream_calls.append((batch_size, start_offset))
        for batch in self.batches:
            yield batch


class FakeNormalizer(ITextNormalizer):
    def normalize(self, text: str) -> str:
        return text.strip()

    async def normalize_async(self, text: str) -> str:
        return text.strip()

    def normalize_batch(self, texts: Sequence[str]) -> list[str]:
        return [t.strip() for t in texts]

    async def normalize_batch_async(self, texts: Sequence[str]) -> list[str]:
        return [t.strip() for t in texts]


class FakeChunker(ISuggestionChunker):
    async def chunk(self, document: Suggestion) -> list[Chunk[SuggestionChunkMetadata]]:
        return [
            Chunk[SuggestionChunkMetadata](
                chunk_id=f"{document.id}-title",
                parent_id=document.id,
                content=document.content.title,
                metadata=SuggestionChunkMetadata(
                    chunk_type=SuggestionChunkType.TITLE,
                    sub_index=0,
                    status=document.evaluation.status,
                    context_title=document.context_title,
                ),
            ),
            Chunk[SuggestionChunkMetadata](
                chunk_id=f"{document.id}-problem",
                parent_id=document.id,
                content=document.content.problem,
                metadata=SuggestionChunkMetadata(
                    chunk_type=SuggestionChunkType.PROBLEM,
                    sub_index=1,
                    status=document.evaluation.status,
                    context_title=document.context_title,
                ),
            ),
        ]


class FakeDenseEmbedder(IDenseEmbedder):
    @property
    def embedding_dimension(self) -> int:
        return 768

    async def embed_query(self, query: str, truncate: bool = True) -> list[float]:
        return [0.1] * 768

    async def embed_documents(
        self, texts: Sequence[str], truncate: bool = True
    ) -> list[list[float]]:
        return [[0.2] * 768 for _ in texts]


class FakeSparseEmbedder(ISparseEmbedder):
    async def embed_document(self, text: str) -> SparseVector:
        return SparseVector(indices=[1], values=[1.0])

    async def embed_query(self, query: str) -> SparseVector:
        return SparseVector(indices=[1], values=[1.0])

    async def embed_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        return [SparseVector(indices=[1, 2], values=[0.5, 0.8]) for _ in texts]


class FakeVectorRepo(ISuggestionVectorRepository):
    def __init__(self):
        self.upserted_chunks: list[Chunk[SuggestionChunkMetadata]] = []
        self.deleted_parent_ids: list[str] = []
        self.activated_parent_ids: list[str] = []
        self.should_fail = False

    async def upsert_chunk(self, chunk: Chunk[SuggestionChunkMetadata]) -> None:
        if self.should_fail:
            raise VectorStorageError("Qdrant cluster unavailable")
        self.upserted_chunks.append(chunk)

    async def upsert_chunks_batch(
        self, chunks: Sequence[Chunk[SuggestionChunkMetadata]]
    ) -> None:
        if self.should_fail:
            raise VectorStorageError("Qdrant cluster unavailable")
        self.upserted_chunks.extend(chunks)

    async def provision_collection(self, dense_dimension: int | None = None) -> None:
        pass

    async def delete_chunks_by_parent_id(self, parent_id: str) -> None:
        self.deleted_parent_ids.append(parent_id)

    async def delete_chunks_by_parent_ids(self, parent_ids: Sequence[str]) -> None:
        self.deleted_parent_ids.extend(parent_ids)

    async def delete_staging_chunks(self, parent_id: str) -> None:
        pass

    async def activate_staging_chunks(self, parent_id: str) -> None:
        self.activated_parent_ids.append(parent_id)

    async def activate_staging_chunks_batch(self, parent_ids: Sequence[str]) -> None:
        self.activated_parent_ids.extend(parent_ids)

    async def delete_deprecated_chunks(self, parent_id: str) -> None:
        pass

    async def delete_chunks_by_ids(self, chunk_ids: Sequence[str]) -> None:
        pass

    async def delete_superseded_chunks(
        self, parent_id: str, active_chunk_ids: Sequence[str]
    ) -> None:
        pass

    async def search_suggestions(self, *args, **kwargs):
        return []


@pytest.fixture
def fake_env():
    sugg_repo = FakeSuggestionRepo()
    cp_repo = FakeCheckpointRepo()
    skip_repo = FakeSkippedRepo()
    uow = FakeUoW(sugg_repo, cp_repo, skip_repo)

    normalizer = FakeNormalizer()
    chunker = FakeChunker()
    dense_embedder = FakeDenseEmbedder()
    sparse_embedder = FakeSparseEmbedder()
    embedding_service = HybridEmbeddingService(dense_embedder, sparse_embedder)
    vector_repo = FakeVectorRepo()

    return {
        "sugg_repo": sugg_repo,
        "cp_repo": cp_repo,
        "skip_repo": skip_repo,
        "uow": uow,
        "normalizer": normalizer,
        "chunker": chunker,
        "dense_embedder": dense_embedder,
        "sparse_embedder": sparse_embedder,
        "embedding_service": embedding_service,
        "vector_repo": vector_repo,
    }


@pytest.mark.asyncio
async def test_successful_clean_batch_ingestion(fake_env):
    batch = [
        RawSuggestionDataDTO(
            suggestion_id="20000//96",
            title="بهینه‌سازی شبکه فوق توزیع",
            problem="افت ولتاژ در ساعات اوج بار در پست انتقال",
            solution="نصب خازن موازی در باس اصلی شبکه",
            status_id=11,  # APPROVED
            committee_scrutiny="تایید",
            committee_scrutiny_id=0,
            description="مورد تایید است",
            shamsi_date="1402/08/15",
            context_title="توزیع نیرو",
        ),
        RawSuggestionDataDTO(
            suggestion_id="20002//97",
            title="سیستم پایش ترانسفورماتور",
            problem="نبود سنسورهای مانیتورینگ حرارتی آنلاین",
            solution="نصب سنسورهای فیبر نوری بر روی ترانس",
            status_id=21,  # PENDING / EXECUTED
            committee_scrutiny="رد",
            committee_scrutiny_id=1,
            description="در فاز آزمایشی",
            shamsi_date="1402/09/01",
            context_title="انتقال نیرو",
        ),
    ]
    extractor = FakeExtractor([batch])

    use_case = ExtractAndIngestHistoricalSuggestionsUseCase(
        uow=fake_env["uow"],
        extractor=extractor,
        normalizer=fake_env["normalizer"],
        chunker=fake_env["chunker"],
        embedding_service=fake_env["embedding_service"],
        vector_repo=fake_env["vector_repo"],
        job_name="test_job",
    )

    result = await use_case.execute(batch_size=200, resume=True, reset=False)

    assert result.total_extracted == 2
    assert result.total_ingested == 2
    assert result.total_chunks == 4
    assert result.total_skipped == 0
    assert result.last_offset == 2
    assert result.last_processed_id == "20002//97"

    # Assert PostgreSQL received suggestions
    assert len(fake_env["sugg_repo"].saved_suggestions) == 2
    assert fake_env["sugg_repo"].saved_suggestions[0].id == "20000//96"
    assert fake_env["sugg_repo"].saved_suggestions[1].id == "20002//97"

    # Assert Qdrant received embedded chunks
    assert len(fake_env["vector_repo"].upserted_chunks) == 4
    assert all(
        c.dense_vector is not None for c in fake_env["vector_repo"].upserted_chunks
    )
    assert all(
        c.sparse_vector is not None for c in fake_env["vector_repo"].upserted_chunks
    )

    # Assert checkpoint committed
    assert fake_env["cp_repo"].checkpoint is not None
    assert fake_env["cp_repo"].checkpoint.last_offset == 2
    assert fake_env["cp_repo"].checkpoint.last_processed_id == "20002//97"


@pytest.mark.asyncio
async def test_corrupted_records_skipped_and_audited(fake_env):
    batch = [
        RawSuggestionDataDTO(
            suggestion_id="201",
            title="پیشنهاد معتبر اول",
            problem="مشکل افت فشار در خط انتقال گاز توربین",
            solution="تعویض رگولاتور اصلی ایستگاه تقلیل فشار",
            status_id=11,
            committee_scrutiny=None,
            description=None,
            shamsi_date="1401/01/01",
            context_title=None,
        ),
        RawSuggestionDataDTO(
            suggestion_id="202",
            title="   ",  # Invalid empty title!
            problem="مشکل فنی",
            solution="راه حل فنی",
            status_id=11,
            committee_scrutiny=None,
            description=None,
            shamsi_date="1401/01/01",
            context_title=None,
        ),
        RawSuggestionDataDTO(
            suggestion_id="203",
            title="پیشنهاد با وضعیت ناشناخته",
            problem="مشکل شبکه",
            solution="راه حل شبکه",
            status_id=99999,  # Invalid status ID
            committee_scrutiny=None,
            description=None,
            shamsi_date=None,
            context_title=None,
        ),
    ]
    extractor = FakeExtractor([batch])

    use_case = ExtractAndIngestHistoricalSuggestionsUseCase(
        uow=fake_env["uow"],
        extractor=extractor,
        normalizer=fake_env["normalizer"],
        chunker=fake_env["chunker"],
        embedding_service=fake_env["embedding_service"],
        vector_repo=fake_env["vector_repo"],
        job_name="test_job",
    )

    result = await use_case.execute()

    assert result.total_extracted == 3
    assert result.total_ingested == 1
    assert result.total_skipped == 2
    assert len(fake_env["sugg_repo"].saved_suggestions) == 1
    assert fake_env["sugg_repo"].saved_suggestions[0].id == "201"

    # Assert skipped suggestions were persisted to audit repo
    assert len(fake_env["skip_repo"].saved_records) == 2
    skipped_ids = [r.suggestion_id for r in fake_env["skip_repo"].saved_records]
    assert "202" in skipped_ids
    assert "203" in skipped_ids


@pytest.mark.asyncio
async def test_qdrant_failure_triggers_compensating_sql_rollback(fake_env):
    batch = [
        RawSuggestionDataDTO(
            suggestion_id="301",
            title="پیشنهاد تست جبران‌سازی",
            problem="مشکل اساسی در پایداری ولتاژ شبکه",
            solution="نصب استابلایزر و فیلتر هارمونیک",
            status_id=11,
            committee_scrutiny=None,
            description=None,
            shamsi_date="1402/01/01",
            context_title=None,
        ),
    ]
    extractor = FakeExtractor([batch])

    # Simulate Qdrant outage
    fake_env["vector_repo"].should_fail = True

    use_case = ExtractAndIngestHistoricalSuggestionsUseCase(
        uow=fake_env["uow"],
        extractor=extractor,
        normalizer=fake_env["normalizer"],
        chunker=fake_env["chunker"],
        embedding_service=fake_env["embedding_service"],
        vector_repo=fake_env["vector_repo"],
        job_name="test_job",
    )

    with pytest.raises(VectorStorageError, match="Qdrant cluster unavailable"):
        await use_case.execute()

    # Assert compensating delete_batch was invoked on SQL repo
    assert "301" in fake_env["sugg_repo"].deleted_ids

    # Assert checkpoint was NOT saved
    assert fake_env["cp_repo"].watermark is None


@pytest.mark.asyncio
async def test_resume_and_reset_behavior(fake_env):
    fake_env["cp_repo"].checkpoint = CheckpointData(
        last_offset=500, last_processed_id="20009//99", total_processed=500
    )

    extractor = FakeExtractor([])
    use_case = ExtractAndIngestHistoricalSuggestionsUseCase(
        uow=fake_env["uow"],
        extractor=extractor,
        normalizer=fake_env["normalizer"],
        chunker=fake_env["chunker"],
        embedding_service=fake_env["embedding_service"],
        vector_repo=fake_env["vector_repo"],
        job_name="test_job",
    )

    # 1. Resume=True: starts at offset 500
    await use_case.execute(resume=True, reset=False)
    assert extractor.stream_calls[-1][1] == 500

    # 2. Reset=True: clears checkpoint and starts at offset 0
    await use_case.execute(resume=True, reset=True)
    assert fake_env["cp_repo"].cleared is True
    assert extractor.stream_calls[-1][1] == 0


@pytest.mark.asyncio
async def test_graceful_stop_signal(fake_env):
    batch_1 = [
        RawSuggestionDataDTO(
            suggestion_id="20010//93",
            title="پیشنهاد بسته اول",
            problem="مشکل افت ولتاژ در باسبار اصلی",
            solution="نصب سیستم تنظیم خودکار تپ ترانس",
            status_id=11,
            committee_scrutiny=None,
            description=None,
            shamsi_date="1402/01/01",
            context_title=None,
        ),
    ]
    batch_2 = [
        RawSuggestionDataDTO(
            suggestion_id="20013//97",
            title="پیشنهاد بسته دوم",
            problem="مشکل عدم هماهنگی رله‌های حفاظتی",
            solution="تنظیم مجدد منحنی جریان زمان رله",
            status_id=11,
            committee_scrutiny=None,
            description=None,
            shamsi_date="1402/01/02",
            context_title=None,
        ),
    ]
    extractor = FakeExtractor([batch_1, batch_2])

    use_case = ExtractAndIngestHistoricalSuggestionsUseCase(
        uow=fake_env["uow"],
        extractor=extractor,
        normalizer=fake_env["normalizer"],
        chunker=fake_env["chunker"],
        embedding_service=fake_env["embedding_service"],
        vector_repo=fake_env["vector_repo"],
        job_name="test_job",
    )

    stop_flag = True  # Stop immediately after batch 1
    result = await use_case.execute(should_stop=lambda: stop_flag)

    # Batch 1 processed, batch 2 not processed
    assert result.total_extracted == 1
    assert result.total_ingested == 1
    assert result.last_offset == 1
    assert result.last_processed_id == "20010//93"
    assert fake_env["cp_repo"].checkpoint is not None
    assert fake_env["cp_repo"].checkpoint.last_offset == 1
    assert fake_env["cp_repo"].checkpoint.last_processed_id == "20010//93"


def test_resolve_suggestion_status_mapping():
    # Normalized Domain IDs (1..5) as emitted by EXTRACTION_QUERY
    assert _resolve_suggestion_status(1) == SuggestionStatus.NOT_ACCEPTED
    assert _resolve_suggestion_status(2) == SuggestionStatus.REJECTED
    assert _resolve_suggestion_status(3) == SuggestionStatus.APPROVED
    assert _resolve_suggestion_status(4) == SuggestionStatus.PENDING
    assert _resolve_suggestion_status(5) == SuggestionStatus.EXECUTED

    # Raw legacy MSSQL IDs
    assert _resolve_suggestion_status(10) == SuggestionStatus.REJECTED
    assert _resolve_suggestion_status(56) == SuggestionStatus.REJECTED
    assert _resolve_suggestion_status(15) == SuggestionStatus.NOT_ACCEPTED
    assert _resolve_suggestion_status(11) == SuggestionStatus.APPROVED
    assert _resolve_suggestion_status(21) == SuggestionStatus.PENDING
    assert _resolve_suggestion_status(13) == SuggestionStatus.EXECUTED

    # Unknown ID raises InvalidSuggestionStatusError
    with pytest.raises(
        InvalidSuggestionStatusError, match="Unknown suggestion status ID: 999"
    ):
        _resolve_suggestion_status(999)


def test_resolve_scrutinies_strict_validation():
    # Committee Scrutiny resolution - valid
    assert _resolve_committee_scrutiny(0, None) == (CommitteeScrutiny.APPROVED, 0)
    assert _resolve_committee_scrutiny(-10, None) == (
        CommitteeScrutiny.SELECT_CONSULTANT_RETURN_FOR_CORRECTION,
        -10,
    )
    assert _resolve_committee_scrutiny(None, "رد") == (CommitteeScrutiny.REJECTED, 1)
    assert _resolve_committee_scrutiny(None, None) == (None, None)
    assert _resolve_committee_scrutiny(None, "   ") == (None, None)

    # Committee Scrutiny resolution - errors on unmapped code/title
    with pytest.raises(InvalidCommitteeScrutinyError):
        _resolve_committee_scrutiny(999, None)
    with pytest.raises(InvalidCommitteeScrutinyError):
        _resolve_committee_scrutiny(None, "عنوان غیر استاندارد")

    # Secretariat Scrutiny resolution - valid
    assert _resolve_secretariat_scrutiny(0, None) == (
        SecretariatScrutiny.OUT_OF_FRAMEWORK,
        0,
    )
    assert _resolve_secretariat_scrutiny(-2, None) == (
        SecretariatScrutiny.SEND_TO_APPROVER,
        -2,
    )
    assert _resolve_secretariat_scrutiny(None, "ارجاع به کمیته") == (
        SecretariatScrutiny.REFER_TO_COMMITTEE,
        3,
    )
    assert _resolve_secretariat_scrutiny(None, None) == (None, None)
    assert _resolve_secretariat_scrutiny(None, "   ") == (None, None)

    # Secretariat Scrutiny resolution - errors on unmapped code/title
    with pytest.raises(InvalidSecretariatScrutinyError):
        _resolve_secretariat_scrutiny(999, None)
    with pytest.raises(InvalidSecretariatScrutinyError):
        _resolve_secretariat_scrutiny(None, "عنوان غیر استاندارد دبیرخانه")


@pytest.mark.asyncio
async def test_historical_ingestion_skips_invalid_scrutiny_records(fake_env):
    batch = [
        RawSuggestionDataDTO(
            suggestion_id="valid-01",
            title="پیشنهاد معتبر",
            problem="مشکل معتبر در تاسیسات",
            solution="راهکار معتبر اجرایی",
            status_id=11,  # APPROVED
            committee_scrutiny_id=0,
            committee_scrutiny="تایید",
            description="توضیحات معتبر",
            shamsi_date="1402/01/01",
            context_title="ستاد",
        ),
        RawSuggestionDataDTO(
            suggestion_id="invalid-com-01",
            title="پیشنهاد با بررسی نامعتبر کمیته",
            problem="مشکل شبکه",
            solution="راه حل شبکه",
            status_id=11,
            committee_scrutiny_id=999,  # Unmapped committee scrutiny code
            committee_scrutiny=None,
            description=None,
            shamsi_date=None,
            context_title=None,
        ),
        RawSuggestionDataDTO(
            suggestion_id="invalid-sec-01",
            title="پیشنهاد با بررسی نامعتبر دبیرخانه",
            problem="مشکل شبکه",
            solution="راه حل شبکه",
            status_id=11,
            committee_scrutiny_id=None,
            committee_scrutiny=None,
            description=None,
            shamsi_date=None,
            context_title=None,
            secretariat_scrutiny="عنوان ناشناخته دبیرخانه",  # Unmapped secretariat scrutiny title
        ),
    ]
    extractor = FakeExtractor([batch])
    use_case = ExtractAndIngestHistoricalSuggestionsUseCase(
        extractor=extractor,
        uow=fake_env["uow"],
        normalizer=fake_env["normalizer"],
        chunker=fake_env["chunker"],
        embedding_service=fake_env["embedding_service"],
        vector_repo=fake_env["vector_repo"],
    )

    result = await use_case.execute(batch_size=10)
    assert result.total_extracted == 3
    assert result.total_ingested == 1
    assert result.total_skipped == 2

    # Verify only the valid suggestion was saved
    assert len(fake_env["sugg_repo"].saved_suggestions) == 1
    assert fake_env["sugg_repo"].saved_suggestions[0].id == "valid-01"

    # Verify skipped suggestions were stored in skipped_repo
    skipped = fake_env["skip_repo"].saved_records
    assert len(skipped) == 2
    skipped_ids = {s.suggestion_id for s in skipped}
    assert "invalid-com-01" in skipped_ids
    assert "invalid-sec-01" in skipped_ids


@pytest.mark.asyncio
async def test_historical_ingestion_with_scrutiny_and_secretariat_fields(fake_env):
    batch = [
        RawSuggestionDataDTO(
            suggestion_id="20050//98",
            title="بهینه‌سازی سیستم‌های هوشمند دیسپاچینگ",
            problem="کمبود ابزارهای مانیتورینگ آنلاین شبکه",
            solution="استقرار پلتفرم جامع SCADA نوین",
            status_id=3,  # APPROVED
            committee_scrutiny_id=0,
            committee_scrutiny="تایید",
            description="مصوب جلسه کارگروه با تخصیص بودجه",
            secretariat_scrutiny_id=3,
            secretariat_scrutiny="ارجاع به کمیته",
            secretariat_comment="تایید مدارک و ارسال به کمیته مربوطه",
            shamsi_date="1402/10/10",
            context_title="دیسپاچینگ",
        )
    ]
    extractor = FakeExtractor([batch])
    use_case = ExtractAndIngestHistoricalSuggestionsUseCase(
        extractor=extractor,
        uow=fake_env["uow"],
        normalizer=fake_env["normalizer"],
        chunker=fake_env["chunker"],
        embedding_service=fake_env["embedding_service"],
        vector_repo=fake_env["vector_repo"],
    )

    result = await use_case.execute(batch_size=10)
    assert result.total_extracted == 1
    assert result.total_ingested == 1

    saved = fake_env["sugg_repo"].saved_suggestions
    assert len(saved) == 1
    entity = saved[0]
    assert entity.id == "20050//98"
    assert entity.evaluation.scrutiny == CommitteeScrutiny.APPROVED
    assert entity.evaluation.scrutiny_id == 0
    assert entity.evaluation.description == "مصوب جلسه کارگروه با تخصیص بودجه"
    assert entity.secretariat_evaluation is not None
    assert (
        entity.secretariat_evaluation.scrutiny == SecretariatScrutiny.REFER_TO_COMMITTEE
    )
    assert entity.secretariat_evaluation.scrutiny_id == 3
    assert (
        entity.secretariat_evaluation.comment == "تایید مدارک و ارسال به کمیته مربوطه"
    )
