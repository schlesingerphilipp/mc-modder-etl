"""Load commit summaries into ChromaDB.

Usage:
    load-summaries input_file [--collection NAME] [--mode full|incremental]

Example:
    load-summaries summaries/output.parquet --mode full
    load-summaries summaries/output.parquet --mode incremental
"""

import argparse
import sys
from pathlib import Path
from typing import List, Literal
import os
import pandas as pd
from openai import OpenAI

from app.utils.logging import LOGGER
from app.vectordb.chroma_config import ChromaConfig

BATCH_SIZE = 100


def prepare_documents(df: pd.DataFrame) -> pd.DataFrame:
    """Deduplicate rows by commit hash and drop rows without summaries.

    Args:
        df: DataFrame with at least 'commit hash' and 'semantic_summary' columns.

    Returns:
        Deduplicated DataFrame with one row per commit, only rows that have
        a non-empty semantic_summary.
    """
    # Filter out null/empty summaries first so dedup keeps a valid summary
    valid = df[
        df["semantic_summary"].notna()
        & (df["semantic_summary"].str.strip() != "")
    ]
    deduped = valid.drop_duplicates(subset=["commit hash"], keep="first")
    return deduped.reset_index(drop=True)


def validate_and_prepare(input_path: Path) -> pd.DataFrame:
    """Read, validate, and prepare documents from a parquet file.

    Args:
        input_path: Path to input parquet file/directory.

    Returns:
        Deduplicated DataFrame ready for upsert, may be empty.

    Raises:
        FileNotFoundError: If input_path doesn't exist.
        ValueError: If required columns are missing.
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    df = pd.read_parquet(input_path)

    required = ["commit hash", "semantic_summary"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    return prepare_documents(df)


def _build_metadata(row: pd.Series) -> dict:
    """Build metadata dict from a DataFrame row."""
    meta = {
        "repo_id": str(row.get("Repo ID", "")),
        "commit_hash": str(row["commit hash"]),
        "commit_message": str(row.get("commit message", "")),
    }
    pr_msg = row.get("PR message")
    if pd.notna(pr_msg):
        meta["pr_message"] = str(pr_msg)
    pr_id = row.get("PR ID")
    if pd.notna(pr_id):
        meta["pr_id"] = str(int(pr_id))
    return meta


def _get_embeddings(texts: List[str], config: ChromaConfig) -> List[List[float]]:
    """Generate embeddings for a list of texts via OpenAI-compatible API.

    Args:
        texts: List of strings to embed.
        config: ChromaConfig with embedding endpoint settings.

    Returns:
        List of embedding vectors (one per input text).
    """
    client = OpenAI(
        base_url=config.embedding_base_url,
        api_key=config.embedding_api_key,
    )
    response = client.embeddings.create(
        model=config.embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


def _upsert_batches(collection, docs: pd.DataFrame, config: ChromaConfig) -> int:
    """Upsert all documents into a collection in batches.

    Returns:
        Number of documents upserted.
    """
    total = 0
    for start in range(0, len(docs), BATCH_SIZE):
        batch = docs.iloc[start : start + BATCH_SIZE]

        ids = batch["commit hash"].tolist()
        documents = batch["semantic_summary"].tolist()
        metadatas = [_build_metadata(row) for _, row in batch.iterrows()]
        embeddings = _get_embeddings(documents, config)

        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        total += len(ids)
        LOGGER.info(f"Upserted batch {start // BATCH_SIZE + 1} ({len(ids)} docs)")

    return total


def load_summaries(
    input_path: Path,
    collection_name: str = None,
    mode: Literal["full", "incremental"] = "full",
) -> int:
    """Read summaries from parquet and load into ChromaDB.

    Args:
        input_path: Path to input parquet file/directory.
        collection_name: Optional collection name override.
        mode: 'full' drops the existing collection and recreates it.
              'incremental' adds only documents whose commit hash is not
              already in the collection.

    Returns:
        Number of documents upserted.
    """
    docs = validate_and_prepare(input_path)
    if docs.empty:
        LOGGER.info("No documents to load after deduplication/filtering.")
        return 0

    config = ChromaConfig(collection_name=collection_name)
    client = config.get_client()

    if mode == "full":
        # Drop and recreate
        try:
            client.delete_collection(name=config.collection_name)
            LOGGER.info(f"Dropped existing collection '{config.collection_name}'")
        except Exception:
            pass  # Collection didn't exist yet
        collection = client.create_collection(name=config.collection_name)
    else:
        # Incremental: get or create, then filter out existing IDs
        collection = client.get_or_create_collection(name=config.collection_name)
        existing_ids = set(collection.get(ids=docs["commit hash"].tolist())["ids"])
        if existing_ids:
            LOGGER.info(f"Skipping {len(existing_ids)} already-loaded commits")
            docs = docs[~docs["commit hash"].isin(existing_ids)].reset_index(drop=True)
            if docs.empty:
                LOGGER.info("All documents already exist in collection.")
                return 0

    total = _upsert_batches(collection, docs, config)
    LOGGER.info(
        f"Loaded {total} documents into collection '{config.collection_name}' (mode={mode})"
    )
    return total


def main() -> int:
    """CLI entry point for loading summaries into ChromaDB."""
    parser = argparse.ArgumentParser(
        description="Load commit summaries into ChromaDB"
    )
    parser.add_argument(
        "input_file", nargs="?", type=Path, help="Path to input parquet file with summaries", default=Path(f"{os.getenv('DB_PATH', '/var/db')}/summaries")
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="ChromaDB collection name (default: from env or 'commit_summaries')",
    )
    parser.add_argument(
        "--mode",
        choices=["full", "incremental"],
        default="full",
        help="Load mode: 'full' drops and recreates the collection, "
             "'incremental' adds only new documents (default: full)",
    )
    args = parser.parse_args()

    try:
        count = load_summaries(
            args.input_file, collection_name=args.collection, mode=args.mode
        )
        LOGGER.info(f"Successfully loaded {count} documents.")
        return 0
    except FileNotFoundError as e:
        LOGGER.error(f"File error: {e}")
        return 1
    except ValueError as e:
        LOGGER.error(f"Validation error: {e}")
        return 1
    except Exception as e:
        LOGGER.error(f"Failed to load summaries: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
