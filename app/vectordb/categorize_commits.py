"""
LLM-Guided Commit Categorization Pipeline

- Batches commit summaries using KMeans (for diversity)
- Uses LLM to discover categories from batches
- Deduplicates categories with LLM
- Assigns each summary to a category with LLM
- Writes output DataFrame partitioned by category to DB_PATH/categorizedsummaries/

Usage:
    poetry run categorize-commits --collection <name> [--output <path>] [--summaries-per-batch N]
"""
import os
import math
import argparse
from pathlib import Path
from typing import List

import json

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from app.utils.logging import LOGGER
from app.vectordb.chroma_config import ChromaConfig
from pydantic import BaseModel
from langchain_openai import ChatOpenAI

CATEGORY_DISCOVERY_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "CATEGORY_DISCOVERY_PROMPT.md")
CATEGORY_DEDUPLICATION_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "CATEGORY_DEDUPLICATION_PROMPT.md")
CATEGORY_ASSIGNMENT_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "CATEGORY_ASSIGNMENT_PROMPT.md")

DB_PATH = os.getenv("DB_PATH", "/var/db/")

def _checkpoint_dir(output_dir: Path) -> Path:
    d = output_dir / "checkpoints"
    d.mkdir(parents=True, exist_ok=True)
    return d

def _load_checkpoint(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        LOGGER.warning(f"Failed to load checkpoint {path}: {e}")
        return None

def _save_checkpoint(path: Path, data):
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    tmp_path.replace(path)

def _delete_checkpoint(path: Path):
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        LOGGER.warning(f"Failed to delete checkpoint {path}: {e}")


class CategoryList(BaseModel):
    categories: list[str]

class CategoryAssignment(BaseModel):
    category: str

def fetch_embeddings(config: ChromaConfig):
    client = config.get_client()
    collection = client.get_collection(name=config.collection_name)
    result = collection.get(include=["embeddings", "metadatas", "documents"])
    ids = result["ids"]
    embeddings = result["embeddings"]
    metadatas = result["metadatas"]
    documents = result["documents"]
    if not ids or embeddings is None or len(embeddings) == 0:
        raise ValueError(f"Collection '{config.collection_name}' is empty or has no embeddings.")
    return ids, np.array(embeddings), metadatas, documents


def batch_summaries_kmeans(embeddings: np.ndarray, summaries_per_batch: int) -> np.ndarray:
    n = embeddings.shape[0]
    k = max(1, math.ceil(n / summaries_per_batch))
    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = kmeans.fit_predict(embeddings)
    return labels


def load_prompt(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


def get_llm(structured_output: type):
    llm = ChatOpenAI(temperature=0, model_name=os.getenv("LMSTUDIO_MODEL", "gpt-oss-20b"), openai_api_base=os.getenv("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1"), openai_api_key=os.getenv("LMSTUDIO_API_KEY", "not-needed"))
    return llm.with_structured_output(structured_output)


def discover_categories(summaries: List[str], batch_labels: np.ndarray, summaries_per_batch: int) -> List[str]:
    prompt_text = load_prompt(CATEGORY_DISCOVERY_PROMPT_PATH)
    llm = get_llm(CategoryList)
    categories = []
    for batch in np.unique(batch_labels):
        batch_summaries = [summaries[i] for i in range(len(summaries)) if batch_labels[i] == batch]
        input_text = prompt_text + "\n" + "\n".join([f"Summary {i+1}: {s}" for i, s in enumerate(batch_summaries)])
        result: CategoryList = llm.invoke(input=input_text)
        LOGGER.info(f"Batch {batch} categories: {result}")
        categories.extend(result.categories)
    return categories


def deduplicate_categories(categories: List[str]) -> List[str]:
    prompt_text = load_prompt(CATEGORY_DEDUPLICATION_PROMPT_PATH)
    llm = get_llm(CategoryList)
    input_text = prompt_text + "\n" + "\n".join([f"- {c}" for c in categories])
    result: CategoryList = llm.invoke(input=input_text)
    LOGGER.info(f"Deduplicated categories: {result}")
    return result.categories


def assign_categories(summaries: List[str], categories: List[str]) -> List[str]:
    prompt_text = load_prompt(CATEGORY_ASSIGNMENT_PROMPT_PATH)
    llm = get_llm(CategoryAssignment)
    assignments = []
    for summary in summaries:
        categories_text = "\n".join([f"- {c}" for c in categories])
        input_text = f"{prompt_text}\nCategories:\n{categories_text}\n\nSummary:\n{summary}"
        result: CategoryAssignment = llm.invoke(input=input_text)
        assignments.append(result.category)
    return assignments

def boil_down_categories(df: pd.DataFrame) -> pd.DataFrame:
    df["cat_count"] = df.groupby("category")["category"].transform("count")
    category_counts = df.groupby("category").size().reset_index(name="count").sort_values("count", ascending=True)
    threshold = 10
    small_cats = category_counts[category_counts["count"] < threshold]["category"].tolist()
    # replace category with "Other" if in small_cats
    df["category"] = df["category"].apply(lambda x: x if x not in small_cats else "Other")
    df = df.drop(columns=["cat_count"])
    return df
    

def build_df(ids, metadatas, summaries, assignments):
    rows = []
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if metadatas and i < len(metadatas) else {}
        rows.append({
            "commit_hash": doc_id,
            "category": assignments[i],
            "semantic_summary": summaries[i],
            "repo_id": meta.get("repo_id", ""),
            "commit_message": meta.get("commit_message", ""),
        })
    df = pd.DataFrame(rows)
    return df


def main():

    parser = argparse.ArgumentParser(description="LLM-guided commit categorization pipeline")
    parser.add_argument("--collection", type=str, required=True, help="ChromaDB collection name")
    parser.add_argument("--output", type=Path, default=None, help="Output parquet file path (default: DB_PATH/categorizedsummaries/categorized.parquet)")
    parser.add_argument("--summaries-per-batch", type=int, default=20, help="Number of summaries per LLM batch (default: 20)")
    parser.add_argument("--overwrite-checkpoints", action="store_true", help="Ignore and overwrite any existing checkpoints (default: resume if found)")
    args = parser.parse_args()

    config = ChromaConfig(collection_name=args.collection)
    ids, embeddings, metadatas, documents = fetch_embeddings(config)
    summaries = documents
    batch_labels = batch_summaries_kmeans(embeddings, args.summaries_per_batch)

    output_dir = args.output or Path(DB_PATH) / "categorizedsummaries"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = _checkpoint_dir(output_dir)

    # Checkpoint paths
    discovery_ckpt = checkpoint_dir / "categories_discovered.json"
    dedup_ckpt = checkpoint_dir / "categories_deduped.json"
    assign_ckpt = checkpoint_dir / "assignments.json"

    # Optionally clear checkpoints
    if args.overwrite_checkpoints:
        for ckpt in [discovery_ckpt, dedup_ckpt, assign_ckpt]:
            _delete_checkpoint(ckpt)

    # Step 1: Discover categories
    categories = _load_checkpoint(discovery_ckpt)
    if categories is not None:
        LOGGER.info(f"Loaded discovered categories from checkpoint: {discovery_ckpt}")
    else:
        LOGGER.info(f"Discovering categories...")
        categories = discover_categories(summaries, batch_labels, args.summaries_per_batch)
        _save_checkpoint(discovery_ckpt, categories)

    # Step 2: Deduplicate categories
    deduped_categories = _load_checkpoint(dedup_ckpt)
    if deduped_categories is not None:
        LOGGER.info(f"Loaded deduplicated categories from checkpoint: {dedup_ckpt}")
    else:
        LOGGER.info(f"Deduplicating categories...")
        deduped_categories = deduplicate_categories(categories)
        _save_checkpoint(dedup_ckpt, deduped_categories)

    LOGGER.info(f"Final categories: {deduped_categories}")

    # Step 3: Assign categories
    assignments = _load_checkpoint(assign_ckpt)
    if assignments is not None:
        LOGGER.info(f"Loaded assignments from checkpoint: {assign_ckpt}")
    else:
        LOGGER.info(f"Assigning categories to summaries...")
        assignments = assign_categories(summaries, deduped_categories)
        _save_checkpoint(assign_ckpt, assignments)

    # Build DataFrame
    df = build_df(ids, metadatas, summaries, assignments)

    df = boil_down_categories(df)

    # Write partitioned by category
    for cat, group in df.groupby("category"):
        cat_dir = output_dir / cat.replace("/", "_")
        cat_dir.mkdir(parents=True, exist_ok=True)
        group.to_parquet(cat_dir / "categorized.parquet", index=False)
        LOGGER.info(f"Wrote {len(group)} rows to {cat_dir / 'categorized.parquet'}")

    # Clean up checkpoints after successful run
    for ckpt in [discovery_ckpt, dedup_ckpt, assign_ckpt]:
        _delete_checkpoint(ckpt)

