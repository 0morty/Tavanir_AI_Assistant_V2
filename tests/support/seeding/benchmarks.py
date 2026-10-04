"""Typed benchmark queries and golden RAG scenarios for retrieval and generation tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.domain.enums import SuggestionStatus
from tests.support.seeding.corpus import (
    CLUSTER_CYBERSECURITY,
    CLUSTER_DISTRIBUTION,
    CLUSTER_METERING,
    CLUSTER_RENEWABLE,
    CLUSTER_TRANSMISSION,
    REG_CHUNK_CYBER_001,
    REG_CHUNK_CYBER_002,
    REG_CHUNK_DIST_001,
    REG_CHUNK_DIST_002,
    REG_CHUNK_METER_001,
    REG_CHUNK_METER_002,
    REG_CHUNK_SOLAR_001,
    REG_CHUNK_SOLAR_002,
    REG_CHUNK_TRANS_001,
    REG_CHUNK_TRANS_002,
)


@dataclass(frozen=True)
class BenchmarkQuery:
    """Encapsulates a golden evaluation query against seeded test databases."""

    name: str
    query_text: str
    target_cluster: str
    expected_suggestion_ids: list[str]
    expected_regulatory_chunk_ids: list[str]
    filter_status: SuggestionStatus | None = None
    filter_context: str | None = None
    negative_suggestion_ids: list[str] = field(default_factory=list)


BENCHMARK_QUERIES: list[BenchmarkQuery] = [
    # 1. Distribution Transformers
    BenchmarkQuery(
        name="transformer_thermal_monitoring_and_oil_tests",
        query_text="سامانه پایش برخط بار حرارتی، دمای روغن و شکست دی‌الکتریک ترانسفورماتورهای توزیع برق",
        target_cluster=CLUSTER_DISTRIBUTION,
        expected_suggestion_ids=["sugg-dist-001", "sugg-dist-004"],
        expected_regulatory_chunk_ids=[REG_CHUNK_DIST_001, REG_CHUNK_DIST_002],
        negative_suggestion_ids=["sugg-solar-001", "sugg-cyber-001", "sugg-meter-001"],
    ),
    # 2. Smart Metering with Status Filter (APPROVED only)
    BenchmarkQuery(
        name="smart_metering_energy_theft_approved",
        query_text="کشف دستکاری، سرقت انرژی و خطای ترانس جریان در کنتورهای هوشمند طرح فهام",
        target_cluster=CLUSTER_METERING,
        expected_suggestion_ids=["sugg-meter-001"],
        expected_regulatory_chunk_ids=[REG_CHUNK_METER_001, REG_CHUNK_METER_002],
        filter_status=SuggestionStatus.APPROVED,
        negative_suggestion_ids=["sugg-trans-001", "sugg-dist-002"],
    ),
    # 3. Renewable Solar Energy
    BenchmarkQuery(
        name="photovoltaic_solar_plants_grid_connection",
        query_text="توسعه نیروگاه‌های خورشیدی فتوولتائیک و ضوابط اتصال اینورتر به شبکه توزیع برق",
        target_cluster=CLUSTER_RENEWABLE,
        expected_suggestion_ids=["sugg-solar-001", "sugg-solar-004"],
        expected_regulatory_chunk_ids=[REG_CHUNK_SOLAR_001, REG_CHUNK_SOLAR_002],
        negative_suggestion_ids=["sugg-dist-003", "sugg-cyber-002"],
    ),
    # 4. Transmission Line & Relay Protection
    BenchmarkQuery(
        name="high_voltage_transmission_relay_coordination",
        query_text="هماهنگی رله‌های حفاظتی دیستانس و اضافه جریان در خطوط انتقال و پست‌های فشار قوی",
        target_cluster=CLUSTER_TRANSMISSION,
        expected_suggestion_ids=["sugg-trans-001", "sugg-trans-004"],
        expected_regulatory_chunk_ids=[REG_CHUNK_TRANS_001, REG_CHUNK_TRANS_002],
        negative_suggestion_ids=["sugg-meter-004", "sugg-solar-002"],
    ),
    # 5. IT / Cybersecurity in SCADA
    BenchmarkQuery(
        name="scada_ot_industrial_cybersecurity",
        query_text="امنیت سایبری شبکه‌های اتوماسیون پست‌های SCADA، دیسپاچینگ و معماری اعتماد صفر",
        target_cluster=CLUSTER_CYBERSECURITY,
        expected_suggestion_ids=["sugg-cyber-001", "sugg-cyber-002"],
        expected_regulatory_chunk_ids=[REG_CHUNK_CYBER_001, REG_CHUNK_CYBER_002],
        negative_suggestion_ids=["sugg-dist-001", "sugg-trans-002"],
    ),
    # 6. Context-Filtered Query (Tehran Distribution)
    BenchmarkQuery(
        name="tehran_distribution_context_filter",
        query_text="سامانه پایش حرارتی ترانسفورماتور و فناوری اینترنت اشیا",
        target_cluster=CLUSTER_DISTRIBUTION,
        expected_suggestion_ids=["sugg-dist-001"],
        expected_regulatory_chunk_ids=[REG_CHUNK_DIST_001],
        filter_context="شرکت توزیع نیروی برق تهران بزرگ",
        negative_suggestion_ids=["sugg-dist-002", "sugg-dist-004"],
    ),
]


def get_benchmark_query(name: str) -> BenchmarkQuery:
    """Retrieves a benchmark query scenario by name."""
    for query in BENCHMARK_QUERIES:
        if query.name == name:
            return query
    raise KeyError(f"Unknown benchmark query name: '{name}'")
