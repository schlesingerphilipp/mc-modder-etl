# Vector DB Module Architecture

## Overview

The `vectordb` module provides functionality for loading and querying commit summaries in the ChromaDB vector database. This enables semantic search, similarity matching, and advanced querying of generated commit summaries.

### Module Location
```
app/vectordb/
├── __init__.py                 # Package stub (empty placeholder)
├── chroma_config.py            # ChromaDB client configuration
└── load_summaries.py           # Load summaries into ChromaDB
```

### Module Responsibilities
- Establish connection to ChromaDB HTTP API
- Load commit summaries from Parquet into vector database collections
- Support full replacement or incremental loading modes
- Prepare documents with appropriate metadata for semantic search

---

## Data Structures (Pydantic Models)

None. This module does not define Pydantic models, as it works directly with Pandas DataFrames and ChromaDB native types.

**Note:** The `CommitSummary` model from `app/git_data/models.py` is used as input schema for the load process but not defined here.

---

## Entry Points and CLI Interfaces

### Poetry Script: `load-summaries`
CLI entry point registered in project root's `pyproject.toml`:

```toml
[tool.poetry.scripts]
load-summaries = "app.vectordb.load_summaries:main"
```

**Usage:**
```bash
poetry run load-summaries <input_path> [--collection NAME] [--mode FULL|INCREMENTAL]

# Examples:
poetry run load-summaries /var/db/summaries/output --mode full
poetry run load-summaries /var/db/summaries/output --mode incremental
```

### Main Function Location
`app/vectordb/load_summaries.py::main()` → returns exit code (0 success, 1 error)

---

## Dependencies

### External Services
1. **ChromaDB HTTP API**
   - Endpoint: configurable via `CHROMA_HOST:PORT`
   - Collection management: create, delete, upsert collections
   - Documents stored with embeddings for semantic similarity search

2. **Pandas + PyArrow**
   - Read partitioned Parquet input files
   - Process and prepare documents for ChromaDB

3. **LangChain** (implicit via configuration)
   - ChromaDB is often used with LangChain's embedding models

### Environment Variables (`/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `CHROMA_HOST` | `chromadb` | ChromaDB host service name |
| `CHROMA_PORT` | `8000` | ChromaDB HTTP port |
| `CHROMA_COLLECTION` | `commit_summaries` | Collection name for commits |

---

## Key Algorithms and Logic

### Document Preparation (`prepare_documents`)
```python
def prepare_documents(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate rows by commit hash and filter empty summaries."""
    
    # Step 1: Filter out null/empty summaries
    valid = df[
        df["semantic_summary"].notna()
        & (df["semantic_summary"].str.strip() != "")
    ]
    
    # Step 2: Deduplicate by commit hash (keep first occurrence)
    deduped = valid.drop_duplicates(subset=["commit hash"], keep="first")
    
    return deduped.reset_index(drop=True)
```

**Purpose:** Ensures only meaningful commits are loaded, removing:
- Commits with empty summaries (failed LLM calls)
- Duplicate commits (in case of retries or re-processing)

---

### Metadata Construction (`_build_metadata`)
```python
def _build_metadata(row: pd.Series) -> dict:
    """Build metadata dict from a DataFrame row for ChromaDB."""
    meta = {
        "repo_id": str(row.get("Repo ID", "")),
        "commit_hash": str(row["commit hash"]),
        "commit_message": str(row.get("commit message", "")),
    }
    
    # Conditionally add PR metadata if present
    pr_msg = row.get("PR message")
    if pd.notna(pr_msg):
        meta["pr_message"] = str(pr_msg)
    
    pr_id = row.get("PR ID")
    if pd.notna(pr_id):
        meta["pr_id"] = str(int(pr_id))
        
    return meta
```

**Purpose:** Adds structured metadata for filtering and semantic search:
- `repo_id`: Repository identifier
- `commit_hash`: Unique commit identifier (used as doc ID)
- `commit_message`: Original commit message text
- `pr_message`: Optional PR description if available
- `pr_id`: Optional numeric PR ID

---

### Batch Upsert Logic (`_upsert_batches`)
```python
def _upsert_batches(collection, docs: pd.DataFrame) -> int:
    """Upsert all documents into a collection in batches.
    
    Args:
        collection: ChromaDB collection instance
        docs: DataFrame with commit hash (ids), semantic_summary (documents),
              and metadata columns
    
    Returns:
        Number of documents upserted
    """
    BATCH_SIZE = 100  # Process in batches of 100 docs
    
    total = 0
    for start in range(0, len(docs), BATCH_SIZE):
        batch = docs.iloc[start : start + BATCH_SIZE]
        
        ids = batch["commit hash"].tolist()
        documents = batch["semantic_summary"].tolist()
        metadatas = [_build_metadata(row) for _, row in batch.iterrows()]
        
        # ChromaDB upsert call
        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        total += len(ids)
        
        LOGGER.info(f"Upserted batch {start // BATCH_SIZE + 1} ({len(ids)} docs)")
    
    return total
```

**Purpose:** Efficient batch loading of summaries into ChromaDB:
- Avoids single-document large payloads
- Provides progress logging per batch
- Handles upsert (insert or update) semantics

---

### Collection Management (`load_summaries`)
```python
def load_summaries(
    input_path: Path,
    collection_name: str = None,
    mode: Literal["full", "incremental"] = "full",
) -> int:
    """Load summaries from parquet into ChromaDB.
    
    Args:
        input_path: Path to partitioned Parquet (file or directory)
        collection_name: Optional override for collection name
        mode: 'full' drops existing collection, 'incremental' adds only new docs
    
    Returns:
        Number of documents upserted
    """
    
    # 1. Read and validate input, prepare documents
    docs = validate_and_prepare(input_path)
    
    if docs.empty:
        LOGGER.info("No documents to load after deduplication/filtering.")
        return 0
    
    # 2. Get ChromaDB client and collection
    config = ChromaConfig(collection_name=collection_name)
    client = config.get_client()
    
    if mode == "full":
        # FULL MODE: Drop existing collection, recreate
        try:
            client.delete_collection(name=config.collection_name)
            LOGGER.info(f"Dropped existing collection '{config.collection_name}'")
        except Exception:
            pass  # Collection didn't exist yet
        
        # Create fresh collection (with embedding model)
        collection = client.create_collection(name=config.collection_name)
        
    else:  # incremental mode
        # INCREMENTAL MODE: Use existing or create new, filter duplicates
        collection = client.get_or_create_collection(name=config.collection_name)
        
        # Get existing doc IDs for this commit_list
        existing_ids = set(
            collection.get(ids=docs["commit hash"].tolist())["ids"]
        )
        
        if existing_ids:
            LOGGER.info(f"Skipping {len(existing_ids)} already-loaded commits")
            
            # Filter out existing docs
            docs = docs[~docs["commit hash"].isin(existing_ids)].reset_index(drop=True)
            
            if docs.empty:
                LOGGER.info("All documents already exist in collection.")
                return 0
    
    # 3. Upsert in batches
    total = _upsert_batches(collection, docs)
    
    LOGGER.info(
        f"Loaded {total} documents into collection '{config.collection_name}' "
        f"(mode={mode})"
    )
    
    return total
```

---

### Mode Comparison

| Aspect | Full Mode | Incremental Mode |
|--------|-----------|------------------|
| Existing collection | Deleted, recreated | Preserved with existing docs |
| Processing time | Slower (embeddings regenerated) | Faster (only new docs embedded) |
| Use case | Fresh start, re-processing all | Streaming updates, partial loads |
| Risk | Loses any prior embeddings | Safe for continuous processing |

---

### Parquet Input Validation (`validate_and_prepare`)

```python
def validate_and_prepare(input_path: Path) -> pd.DataFrame:
    """Read, validate, and prepare documents from Parquet file."""
    
    # 1. Check file/directory exists
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    # 2. Read partitioned Parquet
    df = pd.read_parquet(input_path)
    
    # 3. Validate required columns exist
    required = ["commit hash", "semantic_summary"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    
    return prepare_documents(df)  # Dedup + filter empty
```

**Error Handling:**
- `FileNotFoundError` — Input path doesn't exist
- `ValueError` — Required columns (`commit hash`, `semantic_summary`) missing

