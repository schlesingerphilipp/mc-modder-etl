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
                  │ 2. Sweep k (2..√n)│
                  │ 3. Pick best k   │
                  │ 4. Final KMeans  │
                  │ 5. Write parquet │
                  └──────────────────┘
```

### Algorithm: KMeans + Silhouette Score Sweep

**Why KMeans + Silhouette?**

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| KMeans + Silhouette | Uses existing `scikit-learn`, deterministic, well-understood | Assumes spherical clusters | **Chosen** — embedding spaces are typically well-suited |
| HDBSCAN | Auto-detects k, handles noise, non-spherical clusters | Requires new dependency, more parameters to tune | Rejected — avoids new dependency |
| DBSCAN | Density-based, finds arbitrary shapes | Requires `eps` tuning which is hard to automate | Rejected — harder to get right automatically |
| Elbow method | Visual/heuristic | Subjective, harder to automate than silhouette | Rejected — silhouette gives a single-metric answer |

**How optimal k is found:**

1. Sweep k from `min_k` (default 2) to `min(max_k, √n_samples, n_samples - 1)`
2. For each k, fit `KMeans(n_clusters=k)` and compute `silhouette_score`
3. The k with the **highest silhouette score** wins

The `√n` cap prevents degenerate clusters where most clusters contain a single document. For 100 documents, max k = 10. For 400 documents, max k = 20.

**Silhouette score** (range -1 to +1) measures both:
- **Intra-cluster cohesion** — how close each point is to others in its cluster
- **Inter-cluster separation** — how far each point is from the nearest other cluster

### Output Schema

| Column | Type | Description |
|--------|------|-------------|
| `commit_hash` | string | Commit SHA (document ID from ChromaDB) |
| `cluster_id` | int | Cluster label assigned by KMeans |
| `semantic_summary` | string | The LLM-generated summary text |
| `repo_id` | string | Repository identifier |
| `commit_message` | string | Original git commit message |
| `silhouette_sample_score` | float | Per-sample silhouette score |

**Interpreting `silhouette_sample_score`:**
- **Near +1** — well-matched to its cluster, far from neighboring clusters
- **Near 0** — borderline, close to the decision boundary between clusters
- **Negative** — possibly assigned to the wrong cluster

### CLI Usage

```bash
# Default: cluster the 'commit_summaries' collection, write to /var/db/clusters.parquet
poetry run cluster-summaries

# Specify collection and output
poetry run cluster-summaries --collection my_collection --output /tmp/clusters.parquet

# Constrain cluster range
poetry run cluster-summaries --min-k 3 --max-k 15

# Verbose logging (shows silhouette score per k)
poetry run cluster-summaries -v
```

### Modules

| File | Purpose |
|------|---------|
| `cluster_summaries.py` | Fetch embeddings, find optimal k, cluster, write parquet |
| `chroma_config.py` | Shared ChromaDB connection config |
| `load_summaries.py` | Load summaries + embeddings into ChromaDB (upstream step) |
