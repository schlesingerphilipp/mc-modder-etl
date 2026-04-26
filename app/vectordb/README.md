# Vector DB — Commit Summary Embeddings

Loads LLM-generated commit summaries into ChromaDB with semantic embeddings for vector similarity search.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐
│  Summaries  │────▶│  Workspace   │────▶│ ChromaDB  │
│  (Parquet)  │     │  Container   │     │  Server   │
└─────────────┘     │              │     └───────────┘
                    │ 1. Read data │       stores:
                    │ 2. Embed via │       - documents
                    │    LM Studio │       - embeddings
                    │ 3. Upsert    │       - metadata
                    └──────────────┘
                          │
                          ▼
                    ┌──────────────┐
                    │  LM Studio   │
                    │  /v1/embed   │
                    └──────────────┘
```

Embeddings are generated **client-side** in the workspace container using LM Studio's OpenAI-compatible `/v1/embeddings` endpoint. Pre-computed vectors are sent to ChromaDB via `collection.upsert(embeddings=...)`, so the ChromaDB server does not need its own embedding model — it only stores and indexes vectors.

## Modules

| File | Purpose |
|------|---------|
| `chroma_config.py` | ChromaDB connection + embedding endpoint config from env vars |
| `load_summaries.py` | Read parquet, generate embeddings, upsert into ChromaDB |

## CLI Usage

```bash
# Full mode (drop and recreate collection)
poetry run load-summaries /var/db/summaries --mode full

# Incremental mode (skip existing commits)
poetry run load-summaries /var/db/summaries --mode incremental

# Custom collection name
poetry run load-summaries /var/db/summaries --collection my_collection
```

## Environment Variables

### ChromaDB Connection

| Variable | Default | Description |
|----------|---------|-------------|
| `CHROMA_HOST` | `chromadb` | ChromaDB server hostname |
| `CHROMA_PORT` | `8000` | ChromaDB server port |
| `CHROMA_COLLECTION` | `commit_summaries` | Default collection name |

### Embedding Generation

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_BASE_URL` | Falls back to `LMSTUDIO_BASE_URL`, then `http://host.docker.internal:1234/v1` | OpenAI-compatible embeddings endpoint |
| `EMBEDDING_MODEL` | `text-embedding-nomic-embed-text-v1.5` | Embedding model name |
| `EMBEDDING_API_KEY` | Falls back to `LMSTUDIO_API_KEY`, then `not-needed` | API key for embedding endpoint |

These are set in `.devcontainer/docker-compose.workspace.yml` on the workspace service.

## What Gets Stored in ChromaDB

Each document in the collection represents one commit:

- **id** — commit hash (used for deduplication)
- **document** — the `semantic_summary` text
- **embedding** — vector generated from `semantic_summary` via the embedding model
- **metadata**:
  - `repo_id` — repository identifier
  - `commit_hash` — full SHA
  - `commit_message` — original commit message
  - `pr_message` — PR description (if matched)
  - `pr_id` — PR number (if matched)

## Why Client-Side Embeddings?

ChromaDB can run embeddings server-side, but that requires the full `chromadb` package with `sentence-transformers` installed in the server container. By generating embeddings client-side via LM Studio:

1. The ChromaDB container stays lightweight (`chromadb/chroma:latest`)
2. We reuse the same LM Studio instance used for summarization
3. The embedding model is configurable without rebuilding the ChromaDB container
4. We use `chromadb-client` (thin HTTP client) instead of the full `chromadb` package
