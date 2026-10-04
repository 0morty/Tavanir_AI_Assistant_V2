from __future__ import annotations

import asyncio
import inspect
import json
import sys
import urllib.request
from pathlib import Path

# Add project root to sys.path to enable absolute imports
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

sys.stdout.reconfigure(encoding="utf-8")

# 1. Verify Qdrant Alias Registry via REST
req_alias = urllib.request.Request(
    "http://localhost:7333/aliases",
    headers={"api-key": "tavanir_qdrant_secret_key_2026"},
)
res_alias = urllib.request.urlopen(req_alias)
adata = json.loads(res_alias.read().decode())["result"]
print("Qdrant Alias Registry:", adata)

# 2. Verify Online Repository Search via DI Container
from src.containers import Container


async def verify_search():
    container = Container()
    await container.client_registry.init()
    await container.embedding_client.init()

    dense_embedder = container.dense_embedder()
    if inspect.isawaitable(dense_embedder):
        dense_embedder = await dense_embedder

    sparse_embedder = container.sparse_embedder()
    if inspect.isawaitable(sparse_embedder):
        sparse_embedder = await sparse_embedder

    repo = container.suggestion_vector_repository()
    if inspect.isawaitable(repo):
        repo = await repo

    query = "کاهش تلفات شبکه توزیع نیروی برق"
    dense_vec = await dense_embedder.embed_query(query)
    sparse_vec = await sparse_embedder.embed_query(query)

    results = await repo.search_suggestions(
        dense_vector=dense_vec,
        sparse_vector=sparse_vec,
        limit=3,
    )

    print(f"\nSearch Query: '{query}'")
    print(f"Total Results Found: {len(results)}")
    for i, r in enumerate(results):
        print(
            f"Result {i + 1}: Parent ID: {r.parent_id} | Type: {r.chunk.metadata.chunk_type.value} | Status: {r.chunk.chunk_status.value} | Score: {round(r.score, 4)}"
        )
        print(f"   Snippet: {r.chunk.content[:120]}...")


if __name__ == "__main__":
    asyncio.run(verify_search())
