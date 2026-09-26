from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


def _get_env_file_path() -> str:
    env_file = Path(__file__).resolve().parents[3] / ".env"
    return str(env_file)


def _find_static_directory() -> Path:
    static_dir = Path(__file__).resolve().parents[3] / "src" / "presentation" / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    return static_dir


_base_config = SettingsConfigDict(
    env_file=_get_env_file_path(),
    env_ignore_empty=True,
    extra="ignore",
)


class CoreSettings(BaseSettings):
    model_config = _base_config
    STATIC_DIRECTORY: str = str(_find_static_directory())
    STORAGE_BACKEND: str = "local"  # "s3" or "local"


class LLMSettings(BaseSettings):
    model_config = _base_config

    # API Keys (defaults to 'EMPTY' for local TEI / vLLM)
    TEI_API_KEY: str = "EMPTY"
    VLLM_API_KEY: str = "EMPTY"

    # Base URLs
    TEI_HOST: str = "localhost"
    TEI_PORT: int = 8080
    VLLM_HOST: str = "localhost"
    VLLM_PORT: int = 8000

    # Client configs
    MAX_RETRIES: int = 2

    @property
    def TEI_BASE_URL(self) -> str:  # noqa: N802
        return f"http://{self.TEI_HOST}:{self.TEI_PORT}/v1"

    @property
    def VLLM_BASE_URL(self) -> str:  # noqa: N802
        return f"http://{self.VLLM_HOST}:{self.VLLM_PORT}/v1"


class EmbeddingSettings(BaseSettings):
    model_config = _base_config

    EMBEDDING_PROVIDER: str = "tei"
    EMBEDDING_MODEL: str = "google/embedding-gemma-2b"
    EMBEDDING_DIMENSION: int = 768
    EMBEDDING_BATCH_SIZE: int = 128
    EMBEDDING_TIMEOUT: float = 30.0
    EMBEDDING_QUERY_PREFIX: str = ""
    EMBEDDING_DOCUMENT_PREFIX: str = ""


class GenerationSettings(BaseSettings):
    model_config = _base_config

    # LLM provider used by the Generation API (completions / summarization)
    LLM_PROVIDER: str = "vllm"
    LLM_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"
    LLM_TIMEOUT: float = 60.0
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4096

    # Tokenizer configuration for context overflow handling
    TOKENIZER_MODEL: str = "google/gemma-2b"


class BM25Settings(BaseSettings):
    model_config = _base_config

    BM25_K: float = 1.2
    BM25_B: float = 0.2
    BM25_AVG_LEN: float = 256.0
    BM25_TOKEN_MAX_LENGTH: int = 40


class QdrantSettings(BaseSettings):
    model_config = _base_config

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 7333
    QDRANT_GRPC_PORT: int = 7334
    QDRANT_API_KEY: str | None = None
    QDRANT_PREFER_GRPC: bool = False
    QDRANT_HTTPS: bool = False
    QDRANT_STORAGE_PATH: str = "./data/qdrant_storage"

    # ADR-001 Collection Names & Search Aliases
    QDRANT_SUGGESTION_COLLECTION: str = "tavanir_suggestion_v1"
    QDRANT_SUGGESTION_ALIAS: str = "tavanir_suggestion_active"
    QDRANT_REGULATORY_COLLECTION: str = "tavanir_regulatory_knowledge_v1"

    # Search & Batch Defaults
    QDRANT_BATCH_SIZE: int = 64
    QDRANT_BULK_UPSERT_BATCH_SIZE: int = 256
    QDRANT_DENSE_VECTOR_NAME: str = "dense"
    QDRANT_SPARSE_VECTOR_NAME: str = "sparse"
    QDRANT_DENSE_SCORE_THRESHOLD: float | None = None
    QDRANT_SPARSE_SCORE_THRESHOLD: float | None = None

    # Slice Retry Policy
    QDRANT_MAX_RETRIES: int = 3
    QDRANT_RETRY_BASE_DELAY: float = 0.5
    QDRANT_RETRY_MAX_DELAY: float = 8.0


class DBSettings(BaseSettings):
    model_config = _base_config

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 7432
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_USERNAME: str = "postgres"
    POSTGRES_DB: str = "tavanir_db"
    POSTGRES_STORAGE_PATH: str = "./data/postgres_storage"

    # Pool Settings
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: float = 30.0
    DB_POOL_RECYCLE: int = 1800
    DB_POOL_PRE_PING: bool = True

    @property
    def POSTGRES_URL(self) -> str:  # noqa: N802
        user = quote_plus(self.POSTGRES_USERNAME)
        password = quote_plus(self.POSTGRES_PASSWORD)
        return f"postgresql+asyncpg://{user}:{password}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def POSTGRES_URL_SYNC(self) -> str:  # noqa: N802
        user = quote_plus(self.POSTGRES_USERNAME)
        password = quote_plus(self.POSTGRES_PASSWORD)
        return f"postgresql+psycopg2://{user}:{password}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"


class LoggingSettings(BaseSettings):
    model_config = _base_config

    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "console"  # "console" for dev, "json" for docker/prod
    ENVIRONMENT: str = "development"


class SecuritySettings(BaseSettings):
    API_KEY_NAME: str = "X-API-Key"
    API_KEY: str = "tavanir_default_secret_api_key_2026"

    model_config = _base_config


class MssqlSettings(BaseSettings):
    model_config = _base_config

    MSSQL_SERVER: str = "localhost"
    MSSQL_PORT: int = 1433
    MSSQL_USER: str = "sa"
    MSSQL_PASSWORD: str = "YourStrongPassword123"
    MSSQL_DATABASE: str = "TavanirSuggestionDB"
    MSSQL_BATCH_SIZE: int = 200
    MSSQL_MAX_RETRIES: int = 3
    MSSQL_RETRY_BASE_DELAY: float = 1.0


class HistoricalIngestionSettings(BaseSettings):
    model_config = _base_config

    CHECKPOINT_JOB_NAME: str = "historical_suggestion_ingestion"
    BATCH_SIZE: int = 200
    VALIDATION_PROBE_COUNT: int = 3
    AUTO_SWITCH_ALIAS: bool = True


class RerankerSettings(BaseSettings):
    model_config = _base_config

    RERANKER_HOST: str = "localhost"
    RERANKER_PORT: int = 8081
    RERANKER_API_KEY: str = "EMPTY"
    RERANKER_EXPECTED_MODEL_ID: str = "BAAI/bge-reranker-v2-m3"

    # Runtime parameters
    RERANKER_CLIENT_BATCH_SIZE: int = 32
    RERANKER_MAX_CONCURRENT_REQUESTS: int = 4
    RERANKER_RAW_SCORES: bool = True
    RERANKER_TRUNCATE: bool = True
    RERANKER_TRUNCATION_DIRECTION: str = "Left"

    # Latency SLA & Timeouts
    RERANKER_CONNECT_TIMEOUT: float = 1.0
    RERANKER_READ_TIMEOUT: float = 3.0
    RERANKER_MAX_RETRIES: int = 1
    RERANKER_RETRY_BASE_DELAY: float = 0.1
    RERANKER_RETRY_MAX_DELAY: float = 0.5

    # Observability & Truncation Risk
    RERANKER_TRUNCATION_RISK_CHAR_THRESHOLD: int = 2000

    @property
    def RERANKER_BASE_URL(self) -> str:  # noqa: N802
        return f"http://{self.RERANKER_HOST}:{self.RERANKER_PORT}"


class SuggestionAnalysisSettings(BaseSettings):
    model_config = _base_config

    SUGGESTION_ANALYSIS_SOLUTION_LIMIT: int = 40
    SUGGESTION_ANALYSIS_PROBLEM_LIMIT: int = 25
    SUGGESTION_ANALYSIS_TITLE_LIMIT: int = 15
    SUGGESTION_ANALYSIS_POSITIVE_PROBE_LIMIT: int = 15
    SUGGESTION_ANALYSIS_PENDING_PROBE_LIMIT: int = 10
    SUGGESTION_ANALYSIS_TOP_N_PER_STATUS: int = 3
    SUGGESTION_ANALYSIS_MIN_SCORE_THRESHOLD: float | None = 0.0


core_settings = CoreSettings()
llm_settings = LLMSettings()
generation_settings = GenerationSettings()
embedding_settings = EmbeddingSettings()
bm25_settings = BM25Settings()
qdrant_settings = QdrantSettings()
db_settings = DBSettings()
logging_settings = LoggingSettings()
security_settings = SecuritySettings()
mssql_settings = MssqlSettings()
historical_ingestion_settings = HistoricalIngestionSettings()
reranker_settings = RerankerSettings()
suggestion_analysis_settings = SuggestionAnalysisSettings()
