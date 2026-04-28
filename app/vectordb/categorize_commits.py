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
from typing import List, Dict, Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from app.utils.logging import LOGGER
from app.vectordb.chroma_config import ChromaConfig

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate

CATEGORY_DISCOVERY_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "CATEGORY_DISCOVERY_PROMPT.md")
CATEGORY_DEDUPLICATION_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "CATEGORY_DEDUPLICATION_PROMPT.md")
CATEGORY_ASSIGNMENT_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "CATEGORY_ASSIGNMENT_PROMPT.md")

DB_PATH = os.getenv("DB_PATH", "/var/db/")


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


def llm_chain(prompt_template: str):
    llm = ChatOpenAI(temperature=0, model_name=os.getenv("LMSTUDIO_MODEL", "gpt-oss-20b"), openai_api_base=os.getenv("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1"), openai_api_key=os.getenv("LMSTUDIO_API_KEY", "not-needed"))
    prompt = PromptTemplate.from_template(prompt_template)
    return prompt | llm


def discover_categories(summaries: List[str], batch_labels: np.ndarray, summaries_per_batch: int) -> List[str]:
    prompt_text = load_prompt(CATEGORY_DISCOVERY_PROMPT_PATH)
    chain = llm_chain(prompt_text)
    categories = []
    for batch in np.unique(batch_labels):
        batch_summaries = [summaries[i] for i in range(len(summaries)) if batch_labels[i] == batch]
        input_text = "\n".join([f"Summary {i+1}: {s}" for i, s in enumerate(batch_summaries)])
        result = chain.invoke({"input": input_text})
        LOGGER.info(f"Batch {batch} categories: {result}")
        categories.extend([c.strip("- ") for c in str(result).strip().splitlines() if c.strip()])
    return categories


def deduplicate_categories(categories: List[str]) -> List[str]:
    prompt_text = load_prompt(CATEGORY_DEDUPLICATION_PROMPT_PATH)
    chain = llm_chain(prompt_text)
    input_text = "\n".join([f"- {c}" for c in categories])
    result = chain.invoke({"input": input_text})
    LOGGER.info(f"Deduplicated categories: {result}")
    return [c.strip("- ") for c in str(result).strip().splitlines() if c.strip()]


def assign_categories(summaries: List[str], categories: List[str], batch_labels: np.ndarray) -> List[str]:
    prompt_text = load_prompt(CATEGORY_ASSIGNMENT_PROMPT_PATH)
    chain = llm_chain(prompt_text)
    assignments = [None] * len(summaries)
    for batch in np.unique(batch_labels):
        batch_indices = [i for i in range(len(summaries)) if batch_labels[i] == batch]
        batch_summaries = [summaries[i] for i in batch_indices]
        categories_text = "\n".join([f"- {c}" for c in categories])
        summaries_text = "\n".join([f"{i+1}. {s}" for i, s in enumerate(batch_summaries)])
        input_text = f"Categories:\n{categories_text}\n\nSummaries:\n{summaries_text}"
        result = chain.invoke({"input": input_text})
        # Parse table output
        for i, idx in enumerate(batch_indices):
            # Try to extract the assigned category for each summary
            line = [l for l in str(result).splitlines() if summaries[i] in l]
            if line:
                parts = line[0].split("|")
                if len(parts) > 1:
                    assignments[idx] = parts[-1].strip()
                else:
                    assignments[idx] = "Other"
            else:
                assignments[idx] = "Other"
    return assignments


def main():
    parser = argparse.ArgumentParser(description="LLM-guided commit categorization pipeline")
    parser.add_argument("--collection", type=str, required=True, help="ChromaDB collection name")
    parser.add_argument("--output", type=Path, default=None, help="Output parquet file path (default: DB_PATH/categorizedsummaries/categorized.parquet)")
    parser.add_argument("--summaries-per-batch", type=int, default=20, help="Number of summaries per LLM batch (default: 20)")
    args = parser.parse_args()

    config = ChromaConfig(collection_name=args.collection)
    ids, embeddings, metadatas, documents = fetch_embeddings(config)
    summaries = documents
    batch_labels = batch_summaries_kmeans(embeddings, args.summaries_per_batch)

    LOGGER.info(f"Discovering categories...")
    categories = discover_categories(summaries, batch_labels, args.summaries_per_batch)
    categories = deduplicate_categories(categories)
    LOGGER.info(f"Final categories: {categories}")

    LOGGER.info(f"Assigning categories to summaries...")
    assignments = assign_categories(summaries, categories, batch_labels)

    # Build DataFrame
    rows = []
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if metadatas and i < len(metadatas) else {}
        rows.append({
            "commit_hash": doc_id,
            "category": assignments[i],
            "semantic_summary": summaries[i],
            "repo_id": meta.get("repo_id", ""),
            "commit_message": meta.get("commit_message", ""),
            "embedding": embeddings[i].tolist(),
        })
    df = pd.DataFrame(rows)

    # Write partitioned by category
    output_dir = args.output or Path(DB_PATH) / "categorizedsummaries"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for cat, group in df.groupby("category"):
        cat_dir = output_dir / cat.replace("/", "_")
        cat_dir.mkdir(parents=True, exist_ok=True)
        group.to_parquet(cat_dir / "categorized.parquet", index=False)
        LOGGER.info(f"Wrote {len(group)} rows to {cat_dir / 'categorized.parquet'}")

if __name__ == "__main__":
    main()
