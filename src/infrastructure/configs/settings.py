from pathlib import Path

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
    EMBEDDING_BATCH_SIZE: int = 512
    EMBEDDING_TIMEOUT: float = 30.0
    EMBEDDING_QUERY_PREFIX: str = ""
    EMBEDDING_DOCUMENT_PREFIX: str = ""


class QdrantSettings(BaseSettings):
    model_config = _base_config

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 7333
    QDRANT_GRPC_PORT: int = 7334
    QDRANT_API_KEY: str | None = None
    QDRANT_PREFER_GRPC: bool = False
    QDRANT_HTTPS: bool = False
    QDRANT_STORAGE_PATH: str = "./data/qdrant_storage"

    # ADR-001 Collection Names
    QDRANT_SUGGESTION_COLLECTION: str = "tavanir_suggestion_v1"
    QDRANT_REGULATORY_COLLECTION: str = "tavanir_regulatory_knowledge_v1"

    # Search & Batch Defaults
    QDRANT_BATCH_SIZE: int = 64
    QDRANT_DENSE_VECTOR_NAME: str = "dense"
    QDRANT_SPARSE_VECTOR_NAME: str = "sparse"
    QDRANT_DENSE_SCORE_THRESHOLD: float | None = None
    QDRANT_SPARSE_SCORE_THRESHOLD: float | None = None


core_settings = CoreSettings()
llm_settings = LLMSettings()
embedding_settings = EmbeddingSettings()
qdrant_settings = QdrantSettings()
