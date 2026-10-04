"""Manage only the dedicated local test database project, never development."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from tests.database_safety import (
    GUARD_COLLECTION,
    GUARD_POINT_ID,
    TestDatabaseSafetyError,
    assert_application_settings,
    load_test_config,
    verify_postgres_connection,
    verify_qdrant_client,
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "tavanir-tests"


def initialize_file():
    destination = ROOT / ".env.test"
    if destination.exists():
        return
    contents = (ROOT / ".env.test.example").read_text(encoding="utf-8")
    replacements = {
        "test-only-example-password": secrets.token_hex(24),
        "test-only-example-admin-password": secrets.token_hex(24),
        "test-only-example-vector-key": secrets.token_hex(24),
        "test-only-example-environment": secrets.token_hex(24),
    }
    for placeholder, generated in replacements.items():
        contents = contents.replace(placeholder, generated)
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(contents)
    print("Created ignored .env.test with separate generated credentials.")


def run(command, environment, *, timeout=180):
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise TestDatabaseSafetyError(
            "Test service command failed; check Docker health and the dedicated test configuration"
        )
    return result.stdout


def verify_docker_ownership(environment, *, require_running=False):
    listing = run(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "json",
        ],
        environment,
    )
    containers = [json.loads(line) for line in listing.splitlines() if line.strip()]
    # Every pre-existing project resource must carry our explicit environment
    # label. Never adopt another project's container or volume for cleanup.
    services = set()
    for item in containers:
        details = json.loads(run(["docker", "inspect", item["ID"]], environment))[0]
        labels = details["Config"].get("Labels", {})
        if (
            labels.get("tavanir.environment") != "test"
            or labels.get("com.docker.compose.project") != PROJECT
        ):
            raise TestDatabaseSafetyError(
                "Docker test project ownership is not verified"
            )
        service = labels.get("com.docker.compose.service")
        if service not in {"postgres", "qdrant"}:
            raise TestDatabaseSafetyError(
                "Unexpected service in the dedicated database project"
            )
        if require_running and details["State"].get("Running") is not True:
            raise TestDatabaseSafetyError("Dedicated test service is not running")
        if any(
            mount.get("Type") == "bind" and mount.get("RW")
            for mount in details.get("Mounts", [])
        ):
            raise TestDatabaseSafetyError(
                "Test service has an unexpected writable host bind mount"
            )
        for mount in details.get("Mounts", []):
            if mount.get("Type") == "volume":
                labels = json.loads(
                    run(["docker", "volume", "inspect", mount["Name"]], environment)
                )[0].get("Labels", {})
                if (
                    labels.get("tavanir.environment") != "test"
                    or labels.get("com.docker.compose.project") != PROJECT
                ):
                    raise TestDatabaseSafetyError(
                        "Test container mounts a volume outside its verified test project"
                    )
        required_ports = (
            {"5432/tcp": environment["TEST_POSTGRES_PORT"]}
            if service == "postgres"
            else {
                "6333/tcp": environment["TEST_QDRANT_PORT"],
                "6334/tcp": environment["TEST_QDRANT_GRPC_PORT"],
            }
        )
        if require_running:
            for inner, outer in required_ports.items():
                bindings = details["NetworkSettings"].get("Ports", {}).get(inner) or []
                if bindings != [{"HostIp": "127.0.0.1", "HostPort": outer}]:
                    raise TestDatabaseSafetyError(
                        "Test service port binding does not match its dedicated loopback configuration"
                    )
        services.add(service)
    volumes = run(
        [
            "docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.Name}}",
        ],
        environment,
    ).splitlines()
    for name in volumes:
        labels = json.loads(run(["docker", "volume", "inspect", name], environment))[
            0
        ].get("Labels", {})
        if labels.get("tavanir.environment") != "test":
            raise TestDatabaseSafetyError("Test volume ownership is not verified")
    networks = run(
        [
            "docker",
            "network",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.ID}}",
        ],
        environment,
    ).splitlines()
    for name in networks:
        labels = json.loads(run(["docker", "network", "inspect", name], environment))[
            0
        ].get("Labels", {})
        if labels.get("tavanir.environment") != "test":
            raise TestDatabaseSafetyError("Test network ownership is not verified")
    if require_running and services != {"postgres", "qdrant"}:
        raise TestDatabaseSafetyError(
            "Both dedicated test database services are required"
        )


async def postgres_guard(config, *, inspect_records=False):
    from sqlalchemy import text
    from src.infrastructure.db import create_db_engine

    engine = create_db_engine(config.postgres_url)
    try:
        async with engine.connect() as connection:
            await verify_postgres_connection(connection, config)
            if inspect_records:
                return dict(
                    (
                        await connection.execute(
                            text("""
                    SELECT (SELECT count(*) FROM suggestions) AS suggestions,
                           (SELECT count(*) FROM suggestions WHERE is_deleted = FALSE) AS active_suggestions,
                           (SELECT count(*) FROM suggestions WHERE is_deleted = TRUE) AS deleted_suggestions,
                           (SELECT count(*) FROM ingestion_checkpoints) AS ingestion_checkpoints,
                           (SELECT count(*) FROM skipped_suggestions) AS skipped_suggestions
                """)
                        )
                    )
                    .mappings()
                    .one()
                )
    finally:
        await engine.dispose()


async def provision_qdrant(config):
    from qdrant_client import AsyncQdrantClient, models
    from src.infrastructure.db.repositories import (
        QdrantRegulatoryRepository,
        QdrantSuggestionRepository,
    )

    from src.infrastructure.configs import settings

    assert_application_settings(settings, config)
    client = AsyncQdrantClient(url=config.qdrant_url, api_key=config.q_api_key)
    try:
        if await client.collection_exists(GUARD_COLLECTION):
            await verify_qdrant_client(client, config)
        else:
            await client.create_collection(
                GUARD_COLLECTION,
                vectors_config=models.VectorParams(
                    size=1, distance=models.Distance.COSINE
                ),
            )
            await client.upsert(
                GUARD_COLLECTION,
                points=[
                    models.PointStruct(
                        id=GUARD_POINT_ID,
                        vector=[1.0],
                        payload={
                            "environment": "test",
                            "environment_id": config.environment_id,
                        },
                    )
                ],
                wait=True,
            )
            await verify_qdrant_client(client, config)
        for cls, name in (
            (
                QdrantSuggestionRepository,
                settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
            ),
            (
                QdrantRegulatoryRepository,
                settings.qdrant_settings.QDRANT_REGULATORY_COLLECTION,
            ),
        ):
            repository = cls(
                client=client,
                collection_name=name,
                default_dense_dim=settings.embedding_settings.EMBEDDING_DIMENSION,
            )
            await repository.provision_collection()
        alias = settings.qdrant_settings.QDRANT_SUGGESTION_ALIAS
        collection = settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION
        aliases = (await client.get_aliases()).aliases
        existing = next((item for item in aliases if item.alias_name == alias), None)
        if existing and existing.collection_name != collection:
            raise TestDatabaseSafetyError(
                "Test alias points at an unexpected collection"
            )
        if not existing:
            await client.update_collection_aliases(
                [
                    models.CreateAliasOperation(
                        create_alias=models.CreateAlias(
                            alias_name=alias, collection_name=collection
                        )
                    )
                ]
            )
    finally:
        await client.close()


async def check(config):
    from qdrant_client import AsyncQdrantClient
    from sqlalchemy import text
    from src.infrastructure.configs import settings
    from src.infrastructure.db import create_db_engine

    assert_application_settings(settings, config)
    postgres_records = await postgres_guard(config, inspect_records=True)
    client = AsyncQdrantClient(url=config.qdrant_url, api_key=config.q_api_key)
    try:
        await verify_qdrant_client(client, config)
        counts = {}
        for name in (
            settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION,
            settings.qdrant_settings.QDRANT_REGULATORY_COLLECTION,
        ):
            counts[name] = (await client.count(name, exact=True)).count

        referential_verified = True
        sugg_col = settings.qdrant_settings.QDRANT_SUGGESTION_COLLECTION
        if counts.get(sugg_col, 0) > 0:
            parent_ids = set()
            offset = None
            while True:
                scroll_res, offset = await client.scroll(
                    collection_name=sugg_col,
                    limit=100,
                    offset=offset,
                    with_payload=["parent_id"],
                    with_vectors=False,
                )
                for point in scroll_res:
                    if point.payload and "parent_id" in point.payload:
                        parent_ids.add(point.payload["parent_id"])
                if offset is None:
                    break

            engine = create_db_engine(config.postgres_url)
            try:
                async with engine.connect() as connection:
                    await verify_postgres_connection(connection, config)
                    sql_ids = set(
                        (
                            await connection.execute(
                                text("SELECT id FROM suggestions")
                            )
                        )
                        .scalars()
                        .all()
                    )
            finally:
                await engine.dispose()

            referential_verified = parent_ids.issubset(sql_ids)

        print(
            json.dumps(
                {
                    "postgres_database": config.pg_database,
                    "postgres_role": config.pg_username,
                    "postgres_port": config.pg_port,
                    "qdrant_port": config.q_port,
                    "qdrant_grpc_port": config.q_grpc_port,
                    "test_collections": counts,
                    "postgres_records": postgres_records,
                    "referential_integrity_verified": referential_verified,
                    "environment_markers_verified": True,
                },
                indent=2,
            )
        )
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "up", "check", "seed", "down"))
    parser.add_argument(
        "--volumes",
        action="store_true",
        help="Also remove verified test volumes when using down",
    )
    parser.add_argument(
        "--live-embeddings",
        action="store_true",
        help="Generate embeddings via running TEI service instead of deterministic offline vectors",
    )
    args = parser.parse_args()
    if args.volumes and args.command != "down":
        parser.error("--volumes applies only to down")
    if args.live_embeddings and args.command != "seed":
        parser.error("--live-embeddings applies only to seed")
    initialize_file()
    config = load_test_config(ROOT)
    environment = {
        **os.environ,
        **config.compose_environment(),
        **config.application_environment(),
    }
    # Only this child process receives test application settings. Development's
    # .env file and the user's invoking shell remain untouched.
    os.environ.update(config.application_environment())
    compose = [
        "docker",
        "compose",
        "--env-file",
        str(ROOT / ".env.test"),
        "-p",
        PROJECT,
        "-f",
        str(ROOT / "docker-compose.test.yaml"),
    ]
    if args.command == "init":
        print("Dedicated test configuration is valid.")
        return
    verify_docker_ownership(
        environment, require_running=args.command in ("check", "seed")
    )
    if args.command == "up":
        run(
            compose
            + ["up", "-d", "--wait", "--wait-timeout", "120", "--pull", "never"],
            environment,
        )
        verify_docker_ownership(environment, require_running=True)
        asyncio.run(postgres_guard(config))
        run([sys.executable, "-m", "alembic", "upgrade", "head"], environment)
        print("Applied migrations to the verified test database.")
        asyncio.run(provision_qdrant(config))
        asyncio.run(check(config))
    elif args.command == "check":
        asyncio.run(check(config))
    elif args.command == "seed":
        from tests.support.seeding.seeder import run_seeder

        asyncio.run(run_seeder(config, live_embeddings=args.live_embeddings))
        asyncio.run(check(config))
    else:
        run(compose + ["down"] + (["--volumes"] if args.volumes else []), environment)
        print("Stopped only the verified dedicated test database project.")


if __name__ == "__main__":
    try:
        main()
    except TestDatabaseSafetyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    except Exception:
        print(
            "Test database operation failed; development services were not selected.",
            file=sys.stderr,
        )
        raise SystemExit(2)
