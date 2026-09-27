from __future__ import annotations

import structlog

from src.application.dtos import (
    AnalyzeSuggestionDTO,
    AnalyzeSuggestionResponse,
    BulkDeleteErrorItemDTO,
    BulkDeleteResultDTO,
    BulkDeleteSuggestionsDTO,
    CreateSuggestionDTO,
    DeleteSuggestionResponseDTO,
    IngestSuggestionResponseDTO,
    PatchSuggestionDTO,
    UpdateSuggestionDTO,
    UpdateSuggestionResponseDTO,
)
from src.application.use_cases import (
    AnalyzeSuggestionUseCase,
    BulkDeleteSuggestionsUseCase,
    DeleteSuggestionUseCase,
    IngestSuggestionUseCase,
    UpdateSuggestionUseCase,
)
from src.domain.entities import (
    CommitteeEvaluation,
    SecretariatEvaluation,
    ShamsiDate,
    Suggestion,
    SuggestionContent,
)
from src.domain.enums import SuggestionStatus
from src.domain.exceptions import (
    SuggestionAlreadyExistsError,
    SuggestionNotFoundError,
)
from src.infrastructure.mocks.in_memory_suggestion_store import (
    InMemorySuggestionStore,
)

logger = structlog.get_logger(__name__)


class MockAnalyzeSuggestionUseCase(AnalyzeSuggestionUseCase):
    """LSP-compliant mock double for AnalyzeSuggestionUseCase."""

    def __init__(self, store: InMemorySuggestionStore) -> None:
        self._store = store

    async def execute(self, dto: AnalyzeSuggestionDTO) -> AnalyzeSuggestionResponse:
        # Step 1: Validate domain invariants (raises InvalidSuggestionContentError on noise/empty)
        SuggestionContent(
            title=dto.title,
            problem=dto.problem,
            solution=dto.solution,
        )

        # Step 2: Read active suggestions from in-memory store
        active_suggestions = await self._store.list_active()

        # Step 3: Partition existing IDs by status
        similar_executed: list[str] = []
        similar_approved: list[str] = []
        similar_pending: list[str] = []
        similar_rejected: list[str] = []
        similar_not_accepted: list[str] = []

        for s in active_suggestions:
            st = s.evaluation.status
            if st == SuggestionStatus.EXECUTED:
                similar_executed.append(s.id)
            elif st == SuggestionStatus.APPROVED:
                similar_approved.append(s.id)
            elif st == SuggestionStatus.PENDING:
                similar_pending.append(s.id)
            elif st == SuggestionStatus.REJECTED:
                similar_rejected.append(s.id)
            elif st == SuggestionStatus.NOT_ACCEPTED:
                similar_not_accepted.append(s.id)

        analysis = (
            f"## ارزیابی و تحلیل سوابق مشابه سازمانی (نسخه آزمایشی / Mock)\n\n"
            f"**عنوان پیشنهاد:** {dto.title}\n\n"
            f"**چالش و صورت مسئله:** {dto.problem}\n\n"
            f"**راهکار پیشنهادی:** {dto.solution}\n\n"
            f"### نتایج تطبیق مفهومی و ساختاری:\n"
            f"فرآیند بازیابی سه‌مسیره و بازرتبه‌بندی با موفقیت انجام شد. "
            f"تعداد {len(similar_executed)} مورد سابقه اجرا شده، {len(similar_approved)} مصوبه سازمانی "
            f"و {len(similar_pending)} پیشنهاد در دست بررسی تطبیق داده شدند. "
            f"پیشنهاد حاضر با توجه به تجارب موفق پیشین، پتانسیل ارتقای کارایی و بهره‌وری شبکه را داراست."
        )

        return AnalyzeSuggestionResponse(
            analysis=analysis,
            similar_executed_ids=similar_executed,
            similar_approved_ids=similar_approved,
            similar_pending_ids=similar_pending,
            similar_rejected_ids=similar_rejected,
            similar_not_accepted_ids=similar_not_accepted,
            applied_statute_ids=[
                "statute-law-1398-art-4",
                "statute-tavanir-circular-402",
            ],
        )


class MockIngestSuggestionUseCase(IngestSuggestionUseCase):
    """LSP-compliant mock double for IngestSuggestionUseCase."""

    def __init__(self, store: InMemorySuggestionStore) -> None:
        self._store = store

    async def execute(
        self, dto: CreateSuggestionDTO
    ) -> IngestSuggestionResponseDTO:
        # Step 1: Pre-check duplicate existence
        if await self._store.exists(dto.suggestion_id, include_deleted=True):
            raise SuggestionAlreadyExistsError(
                f"Suggestion with ID '{dto.suggestion_id}' already exists.",
                pointer="/data/suggestionId",
            )

        # Step 2: Validate domain invariants
        content = SuggestionContent(
            title=dto.title,
            problem=dto.problem,
            solution=dto.solution,
        )

        date_obj = ShamsiDate(dto.shamsi_date) if dto.shamsi_date else None

        secretariat_eval = None
        if (
            dto.secretariat_scrutiny is not None
            or dto.secretariat_comment is not None
        ):
            secretariat_eval = SecretariatEvaluation(
                scrutiny=dto.secretariat_scrutiny,
                comment=dto.secretariat_comment,
                scrutiny_id=dto.secretariat_scrutiny_id,
            )

        suggestion = Suggestion(
            id=dto.suggestion_id,
            content=content,
            evaluation=CommitteeEvaluation(
                status=dto.status,
                scrutiny=dto.committee_scrutiny,
                description=dto.description,
                scrutiny_id=dto.committee_scrutiny_id,
            ),
            date=date_obj,
            context_title=dto.context_title,
            secretariat_evaluation=secretariat_eval,
            version=1,
            is_deleted=False,
        )

        await self._store.upsert(suggestion)

        return IngestSuggestionResponseDTO(
            suggestion_id=dto.suggestion_id,
            chunks_count=4,
            status="CREATED",
        )


class MockUpdateSuggestionUseCase(UpdateSuggestionUseCase):
    """LSP-compliant mock double for UpdateSuggestionUseCase."""

    def __init__(self, store: InMemorySuggestionStore) -> None:
        self._store = store

    async def execute_put(
        self, dto: UpdateSuggestionDTO
    ) -> UpdateSuggestionResponseDTO:
        existing = await self._store.get(dto.suggestion_id, include_deleted=True)
        if existing is None:
            raise SuggestionNotFoundError(
                f"Suggestion with ID '{dto.suggestion_id}' not found.",
                pointer="/data/suggestionId",
            )

        content = SuggestionContent(
            title=dto.title,
            problem=dto.problem,
            solution=dto.solution,
        )

        existing.content = content
        existing.evaluation = CommitteeEvaluation(
            status=dto.status,
            scrutiny=dto.committee_scrutiny,
            description=dto.description,
            scrutiny_id=dto.committee_scrutiny_id,
        )
        if dto.shamsi_date:
            existing.date = ShamsiDate(dto.shamsi_date)
        if dto.context_title is not None:
            existing.context_title = dto.context_title

        if (
            dto.secretariat_scrutiny is not None
            or dto.secretariat_comment is not None
        ):
            existing.secretariat_evaluation = SecretariatEvaluation(
                scrutiny=dto.secretariat_scrutiny,
                comment=dto.secretariat_comment,
                scrutiny_id=dto.secretariat_scrutiny_id,
            )

        existing.restore()
        existing.increment_version()
        await self._store.upsert(existing)

        return UpdateSuggestionResponseDTO(
            suggestion_id=dto.suggestion_id,
            chunks_count=4,
            version=existing.version,
            status="UPDATED",
        )

    async def execute_patch(
        self, dto: PatchSuggestionDTO
    ) -> UpdateSuggestionResponseDTO:
        existing = await self._store.get(
            dto.suggestion_id, include_deleted=False
        )
        if existing is None:
            raise SuggestionNotFoundError(
                f"Suggestion with ID '{dto.suggestion_id}' not found.",
                pointer="/data/suggestionId",
            )

        title = dto.title if dto.title is not None else existing.content.title
        problem = (
            dto.problem
            if dto.problem is not None
            else existing.content.problem
        )
        solution = (
            dto.solution
            if dto.solution is not None
            else existing.content.solution
        )
        existing.content = SuggestionContent(
            title=title, problem=problem, solution=solution
        )

        if dto.status is not None:
            scrutiny = (
                dto.committee_scrutiny
                if dto.committee_scrutiny is not None
                else existing.evaluation.scrutiny
            )
            desc = (
                dto.description
                if dto.description is not None
                else existing.evaluation.description
            )
            scrutiny_id = (
                dto.committee_scrutiny_id
                if dto.committee_scrutiny_id is not None
                else existing.evaluation.scrutiny_id
            )
            existing.evaluation = CommitteeEvaluation(
                status=dto.status,
                scrutiny=scrutiny,
                description=desc,
                scrutiny_id=scrutiny_id,
            )

        if dto.shamsi_date is not None:
            existing.date = ShamsiDate(dto.shamsi_date)
        if dto.context_title is not None:
            existing.context_title = dto.context_title

        existing.increment_version()
        await self._store.upsert(existing)

        return UpdateSuggestionResponseDTO(
            suggestion_id=dto.suggestion_id,
            chunks_count=4,
            version=existing.version,
            status="UPDATED",
        )

    async def execute(
        self, dto: UpdateSuggestionDTO | PatchSuggestionDTO
    ) -> UpdateSuggestionResponseDTO:
        if isinstance(dto, PatchSuggestionDTO):
            return await self.execute_patch(dto)
        return await self.execute_put(dto)


class MockDeleteSuggestionUseCase(DeleteSuggestionUseCase):
    """LSP-compliant mock double for DeleteSuggestionUseCase."""

    def __init__(self, store: InMemorySuggestionStore) -> None:
        self._store = store

    async def execute(self, suggestion_id: str) -> DeleteSuggestionResponseDTO:
        deleted = await self._store.soft_delete(suggestion_id)
        if not deleted:
            raise SuggestionNotFoundError(
                f"Suggestion with ID '{suggestion_id}' not found.",
                pointer="/data/suggestionId",
            )
        return DeleteSuggestionResponseDTO(
            suggestion_id=suggestion_id,
            status="DELETED",
        )


class MockBulkDeleteSuggestionsUseCase(BulkDeleteSuggestionsUseCase):
    """LSP-compliant mock double for BulkDeleteSuggestionsUseCase."""

    def __init__(self, delete_use_case: DeleteSuggestionUseCase) -> None:
        self._delete_use_case = delete_use_case

    async def execute(
        self, dto: BulkDeleteSuggestionsDTO
    ) -> BulkDeleteResultDTO:
        deleted_ids: list[str] = []
        errors: list[BulkDeleteErrorItemDTO] = []
        total_requested = len(dto.suggestion_ids)

        for index, suggestion_id in enumerate(dto.suggestion_ids):
            pointer = f"/data/suggestionIds/{index}"
            try:
                await self._delete_use_case.execute(suggestion_id)
                deleted_ids.append(suggestion_id)
            except SuggestionNotFoundError as exc:
                errors.append(
                    BulkDeleteErrorItemDTO(
                        suggestion_id=suggestion_id,
                        index=index,
                        code="SUGGESTION_NOT_FOUND",
                        detail=str(exc),
                        source_pointer=pointer,
                    )
                )
            except Exception as exc:
                errors.append(
                    BulkDeleteErrorItemDTO(
                        suggestion_id=suggestion_id,
                        index=index,
                        code="INTERNAL_SERVER_ERROR",
                        detail=str(exc),
                        source_pointer=pointer,
                    )
                )

        return BulkDeleteResultDTO(
            deleted_ids=deleted_ids,
            errors=errors,
            total_requested=total_requested,
            total_deleted=len(deleted_ids),
            total_failed=len(errors),
        )
