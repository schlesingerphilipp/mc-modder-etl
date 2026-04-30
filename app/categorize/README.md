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

---

## Clustering: Semantic Grouping of Commits

### Overview

The `cluster-summaries` command retrieves embedding vectors from ChromaDB and groups commits into semantically similar clusters. This enables discovering patterns like "all rendering fixes" or "build system changes" without manual labeling.

### Data Flow

```
┌───────────┐     ┌──────────────────┐     ┌──────────────┐
│ ChromaDB  │────▶│  cluster_summaries│────▶│  Parquet     │
│ embeddings│     │                  │     │  clusters.pqt│
└───────────┘     │ 1. Fetch vectors │     └──────────────┘
                  │ 2. HDBSCAN clustering │
                  │ 5. Write parquet │
                  └──────────────────┘
```


### Algorithm: HDBSCAN Clustering

**Why HDBSCAN?**

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| HDBSCAN | Auto-detects number of clusters, handles noise, non-spherical clusters, robust to outliers | Requires new dependency, more parameters to tune | **Chosen** — better for real-world embedding spaces |
| KMeans + Silhouette | Simple, deterministic, well-understood | Assumes spherical clusters, requires k search | Replaced |
| DBSCAN | Density-based, finds arbitrary shapes | Requires `eps` tuning which is hard to automate | Not chosen |
| Elbow method | Visual/heuristic | Subjective, harder to automate | Not chosen |

**How clustering works:**

1. Run HDBSCAN on all embeddings (default `min_cluster_size=5`)
2. HDBSCAN automatically determines the number of clusters and labels noise points as `-1`
3. For each cluster, compute centroid and per-point distance to centroid
4. Output includes all points, with noise points marked as `cluster_id = -1`

### Output Schema


| Column | Type | Description |
|--------|------|-------------|
| `commit_hash` | string | Commit SHA (document ID from ChromaDB) |
| `cluster_id` | int | Cluster label assigned by HDBSCAN (`-1` = noise) |
| `semantic_summary` | string | The LLM-generated summary text |
| `repo_id` | string | Repository identifier |
| `commit_message` | string | Original git commit message |
| `embedding` | list[float] | Embedding vector |
| `distance_to_centroid` | float | Euclidean distance to cluster centroid (NaN for noise) |

**Interpreting `cluster_id`:**
- `>=0` — assigned to a cluster
- `-1` — noise/outlier, not assigned to any cluster

### CLI Usage

```bash
# Default: cluster the 'commit_summaries' collection, write to /var/db/clusters.parquet
poetry run cluster-summaries

# Specify collection and output
poetry run cluster-summaries --collection my_collection --output /tmp/clusters.parquet

# Set minimum cluster size (default 5)
poetry run cluster-summaries --collection my_collection --output /tmp/clusters.parquet

# (min_cluster_size is currently set in code; CLI flag can be added if needed)
```

### Modules

| File | Purpose |
|------|---------|
| `cluster_summaries.py` | Fetch embeddings, find optimal k, cluster, write parquet |
| `chroma_config.py` | Shared ChromaDB connection config |
| `load_summaries.py` | Load summaries + embeddings into ChromaDB (upstream step) |
