"""Cluster commit summary embeddings from ChromaDB using KMeans + Silhouette.

Retrieves embedding vectors from a ChromaDB collection, finds the optimal
number of clusters via silhouette score sweep, and outputs cluster assignments
as a parquet file.

Usage:
    cluster-summaries [--collection NAME] [--output PATH] [--min-k N] [--max-k N]

Example:
    cluster-summaries --collection commit_summaries --output /var/db/clusters.parquet
"""

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_samples, silhouette_score

from app.utils.logging import LOGGER
from app.vectordb.chroma_config import ChromaConfig


def fetch_embeddings(
    config: ChromaConfig,
) -> Tuple[List[str], np.ndarray, List[dict], List[str]]:
    """Retrieve all embeddings, IDs, metadata, and documents from a ChromaDB collection.

    Args:
        config: ChromaConfig with connection and collection settings.

    Returns:
        Tuple of (ids, embeddings_array, metadatas, documents).

    Raises:
        ValueError: If the collection is empty or has no embeddings.
    """
    client = config.get_client()
    collection = client.get_collection(name=config.collection_name)

    result = collection.get(include=["embeddings", "metadatas", "documents"])

    ids = result["ids"]
    embeddings = result["embeddings"]
    metadatas = result["metadatas"]
    documents = result["documents"]

    if not ids or embeddings is None or len(embeddings) == 0:
        raise ValueError(
            f"Collection '{config.collection_name}' is empty or has no embeddings."
        )

    return ids, np.array(embeddings), metadatas, documents


def find_optimal_clusters(
    embeddings: np.ndarray, min_k: int = 2, max_k: int = 200
) -> Tuple[int, Dict[int, float]]:
    """Find the optimal number of clusters using silhouette score sweep.

    Sweeps KMeans from min_k to min(max_k, sqrt(n)) and returns the k with
    the highest silhouette score.

    Args:
        embeddings: 2D array of shape (n_samples, n_features).
        min_k: Minimum number of clusters to try.
        max_k: Maximum number of clusters to try (capped at sqrt(n)).

    Returns:
        Tuple of (best_k, scores_dict) where scores_dict maps k -> silhouette score.

    Raises:
        ValueError: If there are too few samples to cluster.
    """
    n_samples = embeddings.shape[0]
    if n_samples < min_k:
        raise ValueError(
            f"Need at least {min_k} samples to cluster, got {n_samples}."
        )

    # Cap max_k at sqrt(n) to avoid degenerate single-doc clusters
    effective_max_k = min(max_k, int(math.sqrt(n_samples)), n_samples - 1)
    effective_max_k = max(effective_max_k, min_k)

    LOGGER.info(
        f"Sweeping k={min_k}..{effective_max_k} for {n_samples} samples"
    )

    scores = {}
    for k in range(min_k, effective_max_k + 1):
        kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
        labels = kmeans.fit_predict(embeddings)
        score = silhouette_score(embeddings, labels)
        scores[k] = score
        LOGGER.debug(f"k={k}: silhouette={score:.4f}")

    best_k = max(scores, key=scores.get)
    LOGGER.info(
        f"Optimal k={best_k} with silhouette={scores[best_k]:.4f}"
    )

    return best_k, scores


def cluster_embeddings(embeddings: np.ndarray, k: int) -> np.ndarray:
    """Run KMeans with given k and return cluster labels.

    Args:
        embeddings: 2D array of shape (n_samples, n_features).
        k: Number of clusters.

    Returns:
        Array of cluster labels of shape (n_samples,).
    """
    kmeans = KMeans(n_clusters=k, n_init=10, random_state=42)
    return kmeans.fit_predict(embeddings)


def build_cluster_dataframe(
    ids: List[str],
    labels: np.ndarray,
    metadatas: List[dict],
    documents: List[str],
    embeddings: np.ndarray,
) -> pd.DataFrame:
    """Assemble a DataFrame with cluster assignments and per-sample silhouette scores.

    Args:
        ids: Document IDs (commit hashes).
        labels: Cluster labels from KMeans.
        metadatas: List of metadata dicts from ChromaDB.
        documents: List of document texts (semantic summaries).
        embeddings: Embedding vectors for computing per-sample silhouette.

    Returns:
        DataFrame with columns: commit_hash, cluster_id, semantic_summary,
        repo_id, commit_message, silhouette_sample_score.
    """
    sample_scores = silhouette_samples(embeddings, labels)

    # Compute cluster centroids
    unique_labels = np.unique(labels)
    centroids = np.zeros((len(unique_labels), embeddings.shape[1]))
    for idx, label in enumerate(unique_labels):
        centroids[idx] = embeddings[labels == label].mean(axis=0)
    label_to_centroid = {label: centroids[i] for i, label in enumerate(unique_labels)}

    rows = []
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if metadatas and i < len(metadatas) else {}
        cluster_id = int(labels[i])
        centroid = label_to_centroid[cluster_id]
        abs_distance = float(np.linalg.norm(embeddings[i] - centroid))
        rows.append(
            {
                "commit_hash": doc_id,
                "cluster_id": cluster_id,
                "semantic_summary": documents[i] if documents else "",
                "repo_id": meta.get("repo_id", ""),
                "commit_message": meta.get("commit_message", ""),
                "silhouette_sample_score": float(sample_scores[i]),
                "embedding": embeddings[i].tolist(),
                "distance_to_centroid": abs_distance,
            }
        )

    return pd.DataFrame(rows)


def cluster_collection(
    collection_name: str = None,
    output_path: Path = None,
    min_k: int = 2,
    max_k: int = 200,
) -> pd.DataFrame:
    """End-to-end: fetch embeddings, find optimal k, cluster, and write parquet.

    Args:
        collection_name: ChromaDB collection name (None uses default).
        output_path: Path to write output parquet. None skips writing.
        min_k: Minimum number of clusters.
        max_k: Maximum number of clusters.

    Returns:
        DataFrame with cluster assignments.
    """
    config = ChromaConfig(collection_name=collection_name)

    LOGGER.info(f"Fetching embeddings from collection '{config.collection_name}'")
    ids, embeddings, metadatas, documents = fetch_embeddings(config)
    LOGGER.info(f"Retrieved {len(ids)} embeddings of dimension {embeddings.shape[1]}")

    best_k, scores = find_optimal_clusters(embeddings, min_k=min_k, max_k=max_k)

    LOGGER.info(f"Clustering with k={best_k}")
    labels = cluster_embeddings(embeddings, best_k)

    df = build_cluster_dataframe(ids, labels, metadatas, documents, embeddings)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        LOGGER.info(f"Wrote {len(df)} rows to {output_path}")

    # Log cluster distribution
    dist = df["cluster_id"].value_counts().sort_index()
    for cid, count in dist.items():
        avg_score = df.loc[df["cluster_id"] == cid, "silhouette_sample_score"].mean()
        LOGGER.info(f"  Cluster {cid}: {count} commits (avg silhouette={avg_score:.4f})")

    return df


def main() -> int:
    """CLI entry point for clustering commit summary embeddings."""
    parser = argparse.ArgumentParser(
        description="Cluster commit summary embeddings from ChromaDB"
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="ChromaDB collection name (default: from env or 'commit_summaries')",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"{os.getenv('DB_PATH', '/var/db')}/cluster/clusters.parquet"),
        help="Output parquet file path (default: /var/db/cluster/clusters.parquet)",
    )
    parser.add_argument(
        "--min-k",
        type=int,
        default=2,
        help="Minimum number of clusters (default: 2)",
    )
    parser.add_argument(
        "--max-k",
        type=int,
        default=200,
        help="Maximum number of clusters (default: 200)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()

    try:
        df = cluster_collection(
            collection_name=args.collection,
            output_path=args.output,
            min_k=args.min_k,
            max_k=args.max_k,
        )
        LOGGER.info(
            f"Successfully clustered {len(df)} commits into "
            f"{df['cluster_id'].nunique()} clusters."
        )
        return 0
    except ValueError as e:
        LOGGER.error(f"Validation error: {e}")
        return 1
    except Exception as e:
        LOGGER.error(f"Failed to cluster: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
