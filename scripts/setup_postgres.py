from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Add project root to sys.path to enable absolute imports
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncpg
from src.infrastructure.configs.settings import db_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("setup_postgres")


async def wait_for_postgres_ready(
    host: str,
    port: int,
    user: str,
    password: str,
    max_retries: int = 15,
    delay: float = 2.0,
) -> asyncpg.Connection:
    """Poll default 'postgres' database until ready or max retries are exceeded."""
    for attempt in range(1, max_retries + 1):
        try:
            conn = await asyncpg.connect(
                user=user,
                password=password,
                database="postgres",
                host=host,
                port=port,
                timeout=5.0,
            )
            logger.info(f"Connected to default 'postgres' database at {host}:{port}.")
            return conn
        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{max_retries}: PostgreSQL not ready yet ({e}). Retrying in {delay}s..."
            )
            await asyncio.sleep(delay)

    raise ConnectionError(
        f"Failed to connect to PostgreSQL at {host}:{port} after {max_retries} attempts."
    )


async def main() -> None:
    logger.info("Starting PostgreSQL database provisioning...")
    target_db = db_settings.POSTGRES_DB
    host = db_settings.POSTGRES_SERVER
    port = db_settings.POSTGRES_PORT
    user = db_settings.POSTGRES_USERNAME
    password = db_settings.POSTGRES_PASSWORD

    logger.info(f"Target database: '{target_db}' at {host}:{port} (User: {user})")

    conn: asyncpg.Connection | None = None
    try:
        conn = await wait_for_postgres_ready(
            host=host,
            port=port,
            user=user,
            password=password,
        )

        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db
        )

        if not exists:
            logger.info(f"Database '{target_db}' does not exist. Creating it...")
            # CREATE DATABASE cannot run inside a transaction block
            await conn.execute(f'CREATE DATABASE "{target_db}"')
            logger.info(f"Successfully created database '{target_db}'.")
        else:
            logger.info(f"Database '{target_db}' already exists. Nothing to do.")

    except Exception as e:
        logger.error(f"PostgreSQL provisioning failed: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if conn is not None and not conn.is_closed():
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
