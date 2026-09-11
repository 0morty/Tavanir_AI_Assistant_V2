from unittest.mock import patch

import pytest
from src.application.interfaces.i_sparse_embedder import ISparseEmbedder
from src.containers import Container
from src.infrastructure.configs.settings import BM25Settings

from src.application.exceptions import SparseEmbedderError
from src.domain.entities import SparseVector
from src.infrastructure.services.embeddings.persian_bm25_embedder import (
    PersianBm25Embedder,
)


@pytest.fixture
def embedder() -> PersianBm25Embedder:
    settings = BM25Settings(
        BM25_K=1.2,
        BM25_B=0.2,
        BM25_AVG_LEN=256.0,
        BM25_TOKEN_MAX_LENGTH=40,
    )
    return PersianBm25Embedder(config=settings)


def test_embedder_implements_interface(embedder: PersianBm25Embedder):
    assert isinstance(embedder, ISparseEmbedder)


@pytest.mark.asyncio
async def test_empty_and_whitespace_document(embedder: PersianBm25Embedder):
    result_empty = await embedder.embed_document("")
    result_whitespace = await embedder.embed_document("   \n\t  ")

    assert isinstance(result_empty, SparseVector)
    assert result_empty.indices == []
    assert result_empty.values == []

    assert isinstance(result_whitespace, SparseVector)
    assert result_whitespace.indices == []
    assert result_whitespace.values == []


@pytest.mark.asyncio
async def test_empty_and_whitespace_query(embedder: PersianBm25Embedder):
    result_empty = await embedder.embed_query("")
    result_whitespace = await embedder.embed_query("   \n  ")

    assert isinstance(result_empty, SparseVector)
    assert result_empty.indices == []
    assert result_empty.values == []

    assert isinstance(result_whitespace, SparseVector)
    assert result_whitespace.indices == []
    assert result_whitespace.values == []


@pytest.mark.asyncio
async def test_empty_batch(embedder: PersianBm25Embedder):
    results = await embedder.embed_documents([])
    assert results == []


@pytest.mark.asyncio
async def test_batch_matches_individual(embedder: PersianBm25Embedder):
    doc1 = "ماده ۱۲: نحوه ارزیابی پیشنهادها در کمیته تخصصی توانیر."
    doc2 = "دستورالعمل اجرایی بهینه‌سازی مصرف انرژی و صرفه‌جویی اقتصادی."

    batch_results = await embedder.embed_documents([doc1, doc2])
    indiv1 = await embedder.embed_document(doc1)
    indiv2 = await embedder.embed_document(doc2)

    assert len(batch_results) == 2
    assert batch_results[0].indices == indiv1.indices
    assert batch_results[0].values == indiv1.values
    assert batch_results[1].indices == indiv2.indices
    assert batch_results[1].values == indiv2.values


@pytest.mark.asyncio
async def test_markdown_and_url_sanitization(embedder: PersianBm25Embedder):
    # Tests that URL is stripped and does not pollute vocabulary,
    # and words inside markdown links are NOT welded to the URL.
    doc = "[سامانه نظام پیشنهادها](https://suggest.tavanir.org.ir/docs)"
    vector = await embedder.embed_document(doc)

    assert len(vector.indices) > 0
    assert len(vector.indices) == len(vector.values)

    # Compute expected token ID for stemmed 'پیشنهاد'
    expected_token_id = PersianBm25Embedder._compute_token_id("پیشنهاد")
    assert expected_token_id in vector.indices

    # Ensure URL components did not enter vocabulary
    for url_word in ["http", "https", "suggest", "tavanir", "org", "ir", "docs"]:
        url_token_id = PersianBm25Embedder._compute_token_id(url_word)
        assert url_token_id not in vector.indices


@pytest.mark.asyncio
async def test_markdown_tables_and_formatting(embedder: PersianBm25Embedder):
    table_doc = """
    ### ماده ۱۵: جدول ارزیابی
    | ردیف | شاخص ارزیابی | حداکثر امتیاز |
    | :--- | :--- | :--- |
    | ۱ | نوآوری | **۳۰** |
    | ۲ | صرفه‌جویی | **۴۰** |
    """
    vector = await embedder.embed_document(table_doc)
    assert len(vector.indices) > 0

    # Table formatting symbols should not exist as token IDs
    for symbol in ["#", "###", "|", "---", ":---", "**"]:
        symbol_id = PersianBm25Embedder._compute_token_id(symbol)
        assert symbol_id not in vector.indices


@pytest.mark.asyncio
async def test_zwnj_preservation(embedder: PersianBm25Embedder):
    doc = "طرح پیشنهادی موجب صرفه‌جویی چشمگیر در مصرف برق شده است."
    vector = await embedder.embed_document(doc)

    # 'صرفه‌جویی' with \u200c should be preserved
    zwnj_token_id = PersianBm25Embedder._compute_token_id("صرفه\u200cجویی")
    assert zwnj_token_id in vector.indices


@pytest.mark.asyncio
async def test_query_embedding_has_flat_unit_weights(embedder: PersianBm25Embedder):
    query = "ارزیابی و بررسی پیشنهادها در خصوص صرفه‌جویی ارزیابی"
    query_vector = await embedder.embed_query(query)

    assert len(query_vector.indices) > 0
    # Every token in the query vector must have exactly 1.0 weight for Qdrant IDF modifier
    assert all(val == 1.0 for val in query_vector.values)


@pytest.mark.asyncio
async def test_document_embedding_tf_saturation(embedder: PersianBm25Embedder):
    # Repeating a term should increase its TF weight, but following BM25 saturation
    doc = "انرژی برق مصرف انرژی و بازدهی انرژی"
    vector = await embedder.embed_document(doc)

    token_map = dict(zip(vector.indices, vector.values, strict=True))
    energy_id = PersianBm25Embedder._compute_token_id(embedder._stemmer("انرژی"))
    bargh_id = PersianBm25Embedder._compute_token_id(embedder._stemmer("برق"))

    assert energy_id in token_map
    assert bargh_id in token_map
    # 'انرژی' appears 3 times, 'برق' appears 1 time -> weight of انرژی > weight of برق
    assert token_map[energy_id] > token_map[bargh_id]


@pytest.mark.asyncio
async def test_indices_are_unsigned_32bit_and_sorted(embedder: PersianBm25Embedder):
    doc = "قوانین و مقررات مربوط به مصوبات هیئت مدیره توانیر."
    vector = await embedder.embed_document(doc)

    # Invariants:
    # 1. Indices must be within [0, 2**32 - 1]
    assert all(0 <= idx < (1 << 32) for idx in vector.indices)
    # 2. Indices must be strictly ascending
    assert vector.indices == sorted(vector.indices)
    # 3. No duplicate indices
    assert len(vector.indices) == len(set(vector.indices))


@pytest.mark.asyncio
async def test_error_handling_raises_sparse_embedder_error(
    embedder: PersianBm25Embedder,
):
    with patch.object(
        embedder._tokenizer, "tokenize", side_effect=RuntimeError("Tokenizer failed")
    ):
        with pytest.raises(SparseEmbedderError, match="Tokenizer failed"):
            await embedder.embed_document("متن تست")

        with pytest.raises(SparseEmbedderError, match="Tokenizer failed"):
            await embedder.embed_query("متن جستجو")

        with pytest.raises(SparseEmbedderError, match="Tokenizer failed"):
            await embedder.embed_documents(["متن تست ۱", "متن تست ۲"])


@pytest.mark.asyncio
async def test_case_folding_for_latin_terms(embedder: PersianBm25Embedder):
    # Tests that SCADA in document matches scada in query
    doc = "سیستم اتوماسیون پست‌های برق با تجهیزات SCADA ارتقا یافت."
    query = "اتوماسیون scada"

    doc_vector = await embedder.embed_document(doc)
    query_vector = await embedder.embed_query(query)

    scada_token_id = PersianBm25Embedder._compute_token_id("scada")
    assert scada_token_id in doc_vector.indices
    assert scada_token_id in query_vector.indices


@pytest.mark.asyncio
async def test_markdown_underscore_delimiters_stripped(embedder: PersianBm25Embedder):
    # Tests that italics/bold underscores do not attach to tokens
    doc = "این یک _آزمایش مهم_ در متدولوژی است."
    query = "آزمایش"

    doc_vector = await embedder.embed_document(doc)
    query_vector = await embedder.embed_query(query)

    azmayesh_id = PersianBm25Embedder._compute_token_id(embedder._stemmer("آزمایش"))
    assert azmayesh_id in doc_vector.indices
    assert azmayesh_id in query_vector.indices

    # Ensure no token ID exists with leading/trailing underscore
    stray_underscore_id = PersianBm25Embedder._compute_token_id("_آزمایش_")
    assert stray_underscore_id not in doc_vector.indices


def test_di_container_wires_sparse_embedder():
    container = Container()
    embedder_instance = container.sparse_embedder()
    assert isinstance(embedder_instance, ISparseEmbedder)
    assert isinstance(embedder_instance, PersianBm25Embedder)
