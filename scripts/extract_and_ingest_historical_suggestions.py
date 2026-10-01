from __future__ import annotations

import argparse
import asyncio
import inspect
import signal
import sys
from pathlib import Path
from typing import Any

# Add project root to sys.path to enable absolute imports
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import structlog
from src.containers import Container
from src.infrastructure.configs.settings import (
    historical_ingestion_settings,
    qdrant_settings,
)
from tqdm import tqdm

from src.infrastructure.configs.logging_setup import configure_logging

# Initialize centralized enterprise logging
configure_logging()
logger = structlog.get_logger("historical_ingest")


async def run_pipeline(
    batch_size: int,
    resume: bool,
    reset: bool,
    skip_gatekeeper: bool,
) -> None:
    container = Container()
    # Selectively initialize only resources needed for ingestion
    await container.client_registry.init()
    await container.embedding_client.init()

    admin_service = container.qdrant_admin_service()
    if inspect.isawaitable(admin_service):
        admin_service = await admin_service

    staging_repo = container.staging_suggestion_vector_repository()
    if inspect.isawaitable(staging_repo):
        staging_repo = await staging_repo

    stop_requested = False

    def handle_signal(sig: int, frame: Any) -> None:
        nonlocal stop_requested
        logger.warning(
            "shutdown_signal_received",
            signal=sig,
            action="Draining current batch before stopping...",
        )
        stop_requested = True

    try:
        signal.signal(signal.SIGINT, handle_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, handle_signal)
    except (ValueError, AttributeError):
        pass

    try:
        # 1. Cluster Readiness Verification
        await admin_service.wait_until_ready()

        # 2. Reset or Provision Collection
        collection_name = qdrant_settings.QDRANT_SUGGESTION_COLLECTION
        if reset:
            await admin_service.delete_collection_if_exists(collection_name)
            await staging_repo.provision_collection()
        else:
            await staging_repo.provision_collection()

        try:
            # 3. Disable HNSW Indexing during bulk ingestion for maximum write throughput
            await admin_service.set_indexing_threshold(collection_name, threshold=0)

            # 4. Setup Progress Tracking
            pbar = tqdm(desc="Ingesting Suggestions", unit="sug", dynamic_ncols=True)

            def on_progress(
                total_extracted: int, total_ingested: int, total_skipped: int
            ) -> None:
                pbar.n = total_ingested
                pbar.set_postfix(
                    extracted=total_extracted,
                    ingested=total_ingested,
                    skipped=total_skipped,
                    refresh=True,
                )

            # 5. Execute Historical Ingestion Use Case
            await logger.ainfo("initializing_historical_ingestion_use_case")
            use_case = container.extract_and_ingest_historical_suggestions_use_case()
            if inspect.isawaitable(use_case):
                use_case = await use_case

            await logger.ainfo(
                "beginning_streaming_ingestion",
                batch_size=batch_size,
                resume=resume,
                reset=reset,
            )
            result = await use_case.execute(
                batch_size=batch_size,
                resume=resume,
                reset=reset,
                on_progress=on_progress,
                should_stop=lambda: stop_requested,
            )
            pbar.close()

            await logger.ainfo(
                "extraction_and_ingestion_complete",
                extracted=result.total_extracted,
                ingested=result.total_ingested,
                chunks=result.total_chunks,
                skipped=result.total_skipped,
                execution_time_seconds=round(result.execution_time_seconds, 2),
            )
        finally:
            # Always re-enable HNSW indexing even if cancelled or on failure
            try:
                await admin_service.set_indexing_threshold(
                    collection_name, threshold=20000
                )
            except Exception as opt_err:
                await logger.awarning(
                    "failed_to_restore_indexing_threshold",
                    collection=collection_name,
                    error=str(opt_err),
                )

        if stop_requested:
            await logger.awarning(
                "ingestion_stopped_early_by_user",
                message="Watermark preserved.",
            )
            return

        # 6. Wait for Index Optimization to Settle
        await admin_service.wait_for_indexing_settled(collection_name)

        # 7. Gatekeeper Hybrid Smoke Tests
        if not skip_gatekeeper and result.total_ingested > 0:
            await logger.ainfo("running_gatekeeper_smoke_tests")
            dense_embedder = container.dense_embedder()
            if inspect.isawaitable(dense_embedder):
                dense_embedder = await dense_embedder

            sparse_embedder = container.sparse_embedder()
            if inspect.isawaitable(sparse_embedder):
                sparse_embedder = await sparse_embedder

            smoke_queries = [
                "کاهش تلفات شبکه توزیع نیروی برق",
                "بهینه‌سازی مصرف انرژی در ساعات اوج بار",
                "سیستم پایش هوشمند ترانسفورماتورها",
            ]
            for query in smoke_queries:
                dense_vec = await dense_embedder.embed_query(query)
                sparse_vec = await sparse_embedder.embed_query(query)
                results = await staging_repo.search_suggestions(
                    dense_vector=dense_vec,
                    sparse_vector=sparse_vec,
                    limit=5,
                )
                await logger.ainfo(
                    "gatekeeper_query_result",
                    query=query,
                    results_count=len(results),
                )
                if not results:
                    raise RuntimeError(
                        f"Gatekeeper smoke test FAILED: 0 results returned for query '{query}'!"
                    )
            await logger.ainfo("gatekeeper_smoke_tests_passed")
        elif result.total_ingested == 0:
            await logger.ainfo("no_records_newly_ingested_skipping_gatekeeper_tests")

        # 8. Atomic Alias Switch (ADR-001) with Zero-Record Safety Guard
        if result.total_ingested == 0 and reset:
            await logger.awarning(
                "ingestion_yielded_zero_records_aborting_alias_cutover",
                target_collection=collection_name,
            )
            return

        alias_name = qdrant_settings.QDRANT_SUGGESTION_ALIAS
        await admin_service.switch_alias(
            alias_name=alias_name,
            target_collection=collection_name,
        )
        await logger.ainfo(
            "alias_switch_completed",
            alias=alias_name,
            target_collection=collection_name,
        )

    finally:
        await container.embedding_client.shutdown()
        await container.client_registry.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Day 0 Cold Start Historical Suggestion Ingestion CLI"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=historical_ingestion_settings.BATCH_SIZE,
        help="Offset batch size (default: from settings or 200)",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Resume from last committed watermark in PostgreSQL (default: True)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        default=False,
        help="Drop target collection and clear PostgreSQL watermark before running",
    )
    parser.add_argument(
        "--skip-gatekeeper",
        action="store_true",
        default=False,
        help="Skip gatekeeper smoke verification before alias switch",
    )

    args = parser.parse_args()
    asyncio.run(
        run_pipeline(
            batch_size=args.batch_size,
            resume=args.resume,
            reset=args.reset,
            skip_gatekeeper=args.skip_gatekeeper,
        )
    )


if __name__ == "__main__":
    main()
