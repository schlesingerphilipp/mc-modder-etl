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
import hdbscan

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



def cluster_embeddings_hdbscan(embeddings: np.ndarray, min_cluster_size: int = 5) -> np.ndarray:
    """Cluster embeddings using HDBSCAN and return cluster labels.

    Args:
        embeddings: 2D array of shape (n_samples, n_features).
        min_cluster_size: Minimum size of clusters; smaller clusters are labeled as noise (-1).

    Returns:
        Array of cluster labels of shape (n_samples,). Noise points are labeled -1.
    """
    if embeddings.shape[0] < min_cluster_size:
        raise ValueError(f"Need at least {min_cluster_size} samples to cluster, got {embeddings.shape[0]}.")
    clusterer = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size)
    labels = clusterer.fit_predict(embeddings)
    LOGGER.info(f"HDBSCAN found {len(set(labels)) - (1 if -1 in labels else 0)} clusters; {sum(labels == -1)} noise points.")
    return labels



# Deprecated: KMeans-based clustering (kept for reference)
def cluster_embeddings(*args, **kwargs):
    raise NotImplementedError("KMeans clustering is no longer supported. Use cluster_embeddings_hdbscan instead.")



def build_cluster_dataframe(
    ids: List[str],
    labels: np.ndarray,
    metadatas: List[dict],
    documents: List[str],
    embeddings: np.ndarray,
) -> pd.DataFrame:
    """Assemble a DataFrame with cluster assignments and distances to centroid.

    Args:
        ids: Document IDs (commit hashes).
        labels: Cluster labels from HDBSCAN.
        metadatas: List of metadata dicts from ChromaDB.
        documents: List of document texts (semantic summaries).
        embeddings: Embedding vectors.

    Returns:
        DataFrame with columns: commit_hash, cluster_id, semantic_summary,
        repo_id, commit_message, embedding, distance_to_centroid.
        Noise points (label -1) are included.
    """
    unique_labels = np.unique(labels[labels != -1])
    centroids = np.zeros((len(unique_labels), embeddings.shape[1]))
    for idx, label in enumerate(unique_labels):
        centroids[idx] = embeddings[labels == label].mean(axis=0)
    label_to_centroid = {label: centroids[i] for i, label in enumerate(unique_labels)}

    rows = []
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if metadatas and i < len(metadatas) else {}
        cluster_id = int(labels[i])
        if cluster_id == -1:
            centroid = np.zeros(embeddings.shape[1])
            abs_distance = float('nan')
        else:
            centroid = label_to_centroid[cluster_id]
            abs_distance = float(np.linalg.norm(embeddings[i] - centroid))
        rows.append(
            {
                "commit_hash": doc_id,
                "cluster_id": cluster_id,
                "semantic_summary": documents[i] if documents else "",
                "repo_id": meta.get("repo_id", ""),
                "commit_message": meta.get("commit_message", ""),
                "embedding": embeddings[i].tolist(),
                "distance_to_centroid": abs_distance,
            }
        )

    return pd.DataFrame(rows)



def cluster_collection(
    collection_name: str = None,
    output_path: Path = None,
    min_cluster_size: int = 5,
) -> pd.DataFrame:
    """End-to-end: fetch embeddings, cluster with HDBSCAN, and write parquet.

    Args:
        collection_name: ChromaDB collection name (None uses default).
        output_path: Path to write output parquet. None skips writing.
        min_cluster_size: Minimum size of clusters for HDBSCAN.

    Returns:
        DataFrame with cluster assignments.
    """
    config = ChromaConfig(collection_name=collection_name)

    LOGGER.info(f"Fetching embeddings from collection '{config.collection_name}'")
    ids, embeddings, metadatas, documents = fetch_embeddings(config)
    LOGGER.info(f"Retrieved {len(ids)} embeddings of dimension {embeddings.shape[1]}")

    labels = cluster_embeddings_hdbscan(embeddings, min_cluster_size=min_cluster_size)

    df = build_cluster_dataframe(ids, labels, metadatas, documents, embeddings)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        LOGGER.info(f"Wrote {len(df)} rows to {output_path}")

    # Log cluster distribution
    dist = df["cluster_id"].value_counts().sort_index()
    for cid, count in dist.items():
        if cid == -1:
            LOGGER.info(f"  Noise: {count} points (unclustered)")
        else:
            LOGGER.info(f"  Cluster {cid}: {count} commits")

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
            min_cluster_size=5,
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
