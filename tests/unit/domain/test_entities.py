import pytest

from src.domain.entities import (
    Chunk,
    CommitteeEvaluation,
    DenseVector,
    QueryEmbedding,
    RegulatoryChunk,
    RegulatoryChunkMetadata,
    RegulatoryDocument,
    RegulatorySearchResult,
    SearchResultChunk,
    SecretariatEvaluation,
    ShamsiDate,
    SparseVector,
    Suggestion,
    SuggestionChunk,
    SuggestionChunkMetadata,
    SuggestionContent,
    SuggestionSearchResult,
)
from src.domain.enums import (
    AuthorityLevel,
    ChunkStatus,
    CommitteeScrutiny,
    RegulatoryDocumentType,
    SecretariatScrutiny,
    SuggestionChunkType,
    SuggestionStatus,
)
from src.domain.exceptions import (
    InvalidShamsiDateFormatError,
    InvalidSparseVectorError,
    InvalidSuggestionContentError,
    VectorPayloadValidationError,
)


def test_dense_vector_typing():
    # DenseVector is a Sequence[float], accepting both lists and tuples
    list_vec: DenseVector = [0.1, 0.2, 0.3]
    tuple_vec: DenseVector = (0.1, 0.2, 0.3)
    assert len(list_vec) == 3
    assert len(tuple_vec) == 3


def test_sparse_vector():
    sv = SparseVector(indices=[1, 5, 10], values=[0.2, 0.8, 1.5])
    assert sv.indices == [1, 5, 10]
    assert sv.values == [0.2, 0.8, 1.5]

    with pytest.raises(InvalidSparseVectorError):
        SparseVector(indices=[1, 2], values=[0.5])

    # Factory method from dict
    sv_from_dict = SparseVector.from_dict({10: 1.5, 1: 0.2, 5: 0.8})
    assert sv_from_dict.indices == [1, 5, 10]
    assert sv_from_dict.values == [0.2, 0.8, 1.5]

    empty_sv = SparseVector.from_dict({})
    assert empty_sv.indices == []
    assert empty_sv.values == []


def test_shamsi_date():
    valid = ShamsiDate("1402/05/20")
    assert str(valid) == "1402/05/20"

    # Month 1-6 allows up to 31 days
    assert str(ShamsiDate("1402/06/31")) == "1402/06/31"

    # Month 7-11 has maximum 30 days; day 31 must raise
    with pytest.raises(InvalidShamsiDateFormatError):
        ShamsiDate("1402/07/31")

    # Month 12 in common year (1402) has 29 days; day 30 must raise
    with pytest.raises(InvalidShamsiDateFormatError):
        ShamsiDate("1402/12/30")

    # Month 12 in leap year (1403) has 30 days; day 30 is valid
    assert str(ShamsiDate("1403/12/30")) == "1403/12/30"

    with pytest.raises(InvalidShamsiDateFormatError):
        ShamsiDate("2024-05-20")

    with pytest.raises(InvalidShamsiDateFormatError):
        ShamsiDate("1402/13/01")


def test_suggestion_entity():
    content = SuggestionContent(
        title="نصب سنسور حرارتی",
        problem="گرم شدن ترانسفورماتور",
        solution="استفاده از سنسورهای بی‌سیم اینترنت اشیا",
    )
    evaluation = CommitteeEvaluation(
        status=SuggestionStatus.APPROVED,
        scrutiny=CommitteeScrutiny.APPROVED,
        description="مصوبه شماره ۲۳",
        scrutiny_id=0,
    )
    suggestion = Suggestion(
        id="SUG-101",
        content=content,
        evaluation=evaluation,
        date=ShamsiDate("1403/02/15"),
        context_title="معاونت انتقال",
    )
    assert suggestion.id == "SUG-101"
    assert suggestion.content.title == "نصب سنسور حرارتی"
    assert suggestion.evaluation.status == SuggestionStatus.APPROVED
    assert suggestion.secretariat_evaluation is None


def test_secretariat_and_committee_evaluation_entities():
    sec_eval = SecretariatEvaluation(
        scrutiny=SecretariatScrutiny.REFER_TO_COMMITTEE,
        comment="بررسی اولیه انجام و به کمیته ارجاع شد.",
        scrutiny_id=3,
    )
    assert sec_eval.scrutiny == SecretariatScrutiny.REFER_TO_COMMITTEE
    assert sec_eval.comment == "بررسی اولیه انجام و به کمیته ارجاع شد."
    assert sec_eval.scrutiny_id == 3

    com_eval = CommitteeEvaluation(
        status=SuggestionStatus.APPROVED,
        scrutiny=CommitteeScrutiny.APPROVED,
        description="مصوب جلسه کارگروه با حداکثر آرا.",
        scrutiny_id=0,
    )
    assert com_eval.status == SuggestionStatus.APPROVED
    assert com_eval.scrutiny == CommitteeScrutiny.APPROVED
    assert com_eval.description == "مصوب جلسه کارگروه با حداکثر آرا."
    assert com_eval.scrutiny_id == 0

    content = SuggestionContent(
        title="تست عنوان",
        problem="تست شرح مشکل",
        solution="تست راهکار پیشنهادی",
    )
    suggestion = Suggestion(
        id="SUG-SEC-COM-1",
        content=content,
        evaluation=com_eval,
        secretariat_evaluation=sec_eval,
        date=ShamsiDate("1402/11/15"),
        context_title="حوزه ستادی",
    )
    assert suggestion.secretariat_evaluation is not None
    assert (
        suggestion.secretariat_evaluation.scrutiny
        == SecretariatScrutiny.REFER_TO_COMMITTEE
    )
    assert suggestion.evaluation.scrutiny_id == 0


def test_suggestion_content_invariants():
    # Valid content
    content = SuggestionContent(
        title="عنوان پیشنهاد تستی",
        problem="مشکل حرارت بیش از حد",
        solution="راهکار بهینه‌سازی فن‌ها",
    )
    assert content.title == "عنوان پیشنهاد تستی"

    # Empty or short fields
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        SuggestionContent(
            title="", problem="مشکل معتبر است", solution="راهکار معتبر است"
        )
    assert exc_info.value.pointer == "/data/title"

    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        SuggestionContent(
            title="عنوان معتبر", problem="  ", solution="راهکار معتبر است"
        )
    assert exc_info.value.pointer == "/data/problem"

    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        SuggestionContent(title="عنوان معتبر", problem="مشکل معتبر", solution="راه")
    assert exc_info.value.pointer == "/data/solution"

    # Noise placeholders
    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        SuggestionContent(
            title="عنوان معتبر", problem="ندارد", solution="راهکار معتبر است"
        )
    assert exc_info.value.pointer == "/data/problem"

    with pytest.raises(InvalidSuggestionContentError) as exc_info:
        SuggestionContent(
            title="عنوان معتبر", problem="مشکل معتبر است", solution="بدون شرح"
        )
    assert exc_info.value.pointer == "/data/solution"


def test_regulatory_document_entity():
    doc = RegulatoryDocument(
        id="REG-1402-01",
        title="آیین‌نامه معاملات توانیر",
        file_name="moamelat.docx",
        content="متن کامل آیین‌نامه معاملات",
    )
    assert doc.id == "REG-1402-01"
    assert doc.title == "آیین‌نامه معاملات توانیر"


def test_chunk_invariant_validation():
    metadata = SuggestionChunkMetadata(chunk_type=SuggestionChunkType.SOLUTION)

    # Empty chunk_id
    with pytest.raises(VectorPayloadValidationError):
        Chunk(
            chunk_id="",
            parent_id="SUG-101",
            content="Valid content",
            metadata=metadata,
        )

    # Empty parent_id
    with pytest.raises(VectorPayloadValidationError):
        Chunk(
            chunk_id="CHK-1",
            parent_id="   ",
            content="Valid content",
            metadata=metadata,
        )

    # Empty content
    with pytest.raises(VectorPayloadValidationError):
        Chunk(
            chunk_id="CHK-1",
            parent_id="SUG-101",
            content="",
            metadata=metadata,
        )


def test_suggestion_chunk_1_to_n_pattern():
    metadata = SuggestionChunkMetadata(
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.APPROVED,
        context_title="معاونت انتقال",
        date=ShamsiDate("1402/08/10"),
    )
    # In 1:N SQL hydration pattern, parent_content is None in Qdrant
    chunk: SuggestionChunk = Chunk(
        chunk_id="SUG-101-SOL",
        parent_id="SUG-101",
        content="استفاده از پهپاد برای پایش خطوط",
        metadata=metadata,
        parent_content=None,
        dense_vector=[0.1, 0.2, 0.3],
        sparse_vector=SparseVector(indices=[1, 2], values=[0.5, 0.7]),
        chunk_status=ChunkStatus.ACTIVE,
    )
    assert chunk.chunk_id == "SUG-101-SOL"
    assert chunk.parent_id == "SUG-101"
    assert chunk.parent_content is None
    assert chunk.metadata.chunk_type == SuggestionChunkType.SOLUTION
    assert chunk.metadata.status == SuggestionStatus.APPROVED


def test_regulatory_chunk_1_to_1_table_pattern():
    metadata = RegulatoryChunkMetadata(
        document_title="آیین‌نامه حریم خطوط انتقال",
        document_type=RegulatoryDocumentType.REGULATION,
        is_binding=True,
        authority_level=AuthorityLevel.BINDING,
    )
    # In 1:1 table pattern, raw markdown table is stored in parent_content
    table_markdown = "| ولتاژ (kV) | حداقل حریم (متر) |\n|---|---|\n| 63 | 13 |"
    chunk: RegulatoryChunk = Chunk(
        chunk_id="REG-101-TBL-1",
        parent_id="REG-101",
        content="[آیین‌نامه حریم > جدول ۱] جدول حداقل فواصل حریم خطوط انتقال",
        metadata=metadata,
        parent_content=table_markdown,
        dense_vector=[0.4, 0.5, 0.6],
        chunk_status=ChunkStatus.ACTIVE,
    )
    assert chunk.chunk_id == "REG-101-TBL-1"
    assert chunk.parent_id == "REG-101"
    assert chunk.parent_content == table_markdown
    assert chunk.metadata.is_binding is True
    assert chunk.metadata.authority_level == AuthorityLevel.BINDING


def test_search_result_chunk_and_parent_id():
    s_meta = SuggestionChunkMetadata(
        chunk_type=SuggestionChunkType.SOLUTION,
        status=SuggestionStatus.APPROVED,
    )
    s_chunk: SuggestionChunk = Chunk(
        chunk_id="SUG-101-SOL",
        parent_id="SUG-101",
        content="حل مسأله",
        metadata=s_meta,
    )
    s_result: SuggestionSearchResult = SearchResultChunk(chunk=s_chunk, score=0.92)
    assert s_result.score == 0.92
    assert s_result.parent_id == "SUG-101"
    assert s_result.chunk.metadata.chunk_type == SuggestionChunkType.SOLUTION

    r_meta = RegulatoryChunkMetadata(
        document_title="قانون مانع‌زدایی",
        document_type=RegulatoryDocumentType.STATUTE,
    )
    r_chunk: RegulatoryChunk = Chunk(
        chunk_id="REG-201-ART-3",
        parent_id="REG-201",
        content="ماده ۳",
        metadata=r_meta,
    )
    r_result: RegulatorySearchResult = SearchResultChunk(chunk=r_chunk, score=0.85)
    assert r_result.score == 0.85
    assert r_result.parent_id == "REG-201"


def test_query_embedding():
    qe = QueryEmbedding(
        text="روش‌های نوین پایش شبکه",
        dense_vector=[0.11, 0.22, 0.33],
        sparse_vector=SparseVector(indices=[5, 9], values=[0.3, 0.7]),
    )
    assert qe.text == "روش‌های نوین پایش شبکه"
    assert len(qe.dense_vector) == 3
    assert qe.sparse_vector is not None
