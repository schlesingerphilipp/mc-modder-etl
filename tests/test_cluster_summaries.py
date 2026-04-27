"""Tests for vectordb cluster_summaries module."""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory

from app.vectordb.cluster_summaries import (
    fetch_embeddings,
    find_optimal_clusters,
    cluster_embeddings,
    build_cluster_dataframe,
    cluster_collection,
)


class TestFetchEmbeddings:
    """Tests for fetching embeddings from ChromaDB."""

    def test_fetch_returns_arrays(self):
        mock_collection = Mock()
        mock_collection.get.return_value = {
            "ids": ["a", "b", "c"],
            "embeddings": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
            "metadatas": [
                {"repo_id": "r1", "commit_message": "m1"},
                {"repo_id": "r1", "commit_message": "m2"},
                {"repo_id": "r2", "commit_message": "m3"},
            ],
            "documents": ["doc1", "doc2", "doc3"],
        }
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection

        config = Mock()
        config.collection_name = "test"
        config.get_client.return_value = mock_client

        ids, embeddings, metadatas, documents = fetch_embeddings(config)

        assert ids == ["a", "b", "c"]
        assert embeddings.shape == (3, 2)
        assert len(metadatas) == 3
        assert documents == ["doc1", "doc2", "doc3"]

    def test_fetch_empty_collection_raises(self):
        mock_collection = Mock()
        mock_collection.get.return_value = {
            "ids": [],
            "embeddings": [],
            "metadatas": [],
            "documents": [],
        }
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection

        config = Mock()
        config.collection_name = "empty"
        config.get_client.return_value = mock_client

        with pytest.raises(ValueError, match="empty or has no embeddings"):
            fetch_embeddings(config)


class TestFindOptimalClusters:
    """Tests for silhouette-based cluster count selection."""

    def _make_clustered_data(self, n_per_cluster=50, n_clusters=3, dim=10):
        """Generate synthetic data with clear cluster structure."""
        rng = np.random.RandomState(42)
        centers = rng.randn(n_clusters, dim) * 10
        data = []
        for center in centers:
            data.append(center + rng.randn(n_per_cluster, dim) * 0.5)
        return np.vstack(data)

    def test_finds_correct_k_for_well_separated_data(self):
        embeddings = self._make_clustered_data(n_per_cluster=50, n_clusters=3)
        best_k, scores = find_optimal_clusters(embeddings, min_k=2, max_k=10)
        assert best_k == 3
        assert scores[3] > scores[2]

    def test_returns_scores_for_all_k(self):
        embeddings = self._make_clustered_data(n_per_cluster=30, n_clusters=2)
        best_k, scores = find_optimal_clusters(embeddings, min_k=2, max_k=5)
        assert all(k in scores for k in range(2, 6))
        assert all(isinstance(v, float) for v in scores.values())

    def test_caps_max_k_at_sqrt_n(self):
        # 9 samples => sqrt(9) = 3, so max_k=20 should cap at 3
        embeddings = self._make_clustered_data(n_per_cluster=3, n_clusters=3)
        best_k, scores = find_optimal_clusters(embeddings, min_k=2, max_k=20)
        assert max(scores.keys()) <= 3

    def test_too_few_samples_raises(self):
        embeddings = np.array([[1.0, 2.0]])
        with pytest.raises(ValueError, match="at least 2 samples"):
            find_optimal_clusters(embeddings, min_k=2, max_k=5)


class TestClusterEmbeddings:
    """Tests for KMeans clustering."""

    def test_returns_correct_shape(self):
        rng = np.random.RandomState(42)
        embeddings = rng.randn(20, 5)
        labels = cluster_embeddings(embeddings, k=3)
        assert labels.shape == (20,)
        assert set(labels).issubset({0, 1, 2})

    def test_deterministic_with_same_seed(self):
        rng = np.random.RandomState(42)
        embeddings = rng.randn(30, 5)
        labels1 = cluster_embeddings(embeddings, k=3)
        labels2 = cluster_embeddings(embeddings, k=3)
        np.testing.assert_array_equal(labels1, labels2)


class TestBuildClusterDataframe:
    """Tests for building the output DataFrame."""

    def test_output_columns_and_shape(self):
        ids = ["hash1", "hash2", "hash3"]
        labels = np.array([0, 1, 0])
        metadatas = [
            {"repo_id": "r1", "commit_message": "m1"},
            {"repo_id": "r1", "commit_message": "m2"},
            {"repo_id": "r2", "commit_message": "m3"},
        ]
        documents = ["summary 1", "summary 2", "summary 3"]
        # Need embeddings for silhouette_samples — use simple distinct vectors
        embeddings = np.array([[0, 0], [10, 10], [1, 0]])

        df = build_cluster_dataframe(ids, labels, metadatas, documents, embeddings)

        assert len(df) == 3
        expected_cols = {
            "commit_hash",
            "cluster_id",
            "semantic_summary",
            "repo_id",
            "commit_message",
            "silhouette_sample_score",
            "embedding",
            "distance_to_centroid",
        }
        assert set(df.columns) == expected_cols
        assert list(df["commit_hash"]) == ids
        assert list(df["cluster_id"]) == [0, 1, 0]
        assert all(isinstance(s, float) for s in df["silhouette_sample_score"])
        assert all(isinstance(e, list) for e in df["embedding"])

    def test_handles_missing_metadata(self):
        # Need n_samples > n_labels for silhouette_samples
        ids = ["hash1", "hash2", "hash3"]
        labels = np.array([0, 1, 0])
        metadatas = [{}, {}, {}]
        documents = ["summary1", "summary2", "summary3"]
        embeddings = np.array([[0.0, 0.0], [10.0, 10.0], [1.0, 0.0]])

        df = build_cluster_dataframe(ids, labels, metadatas, documents, embeddings)

        assert df.iloc[0]["repo_id"] == ""
        assert df.iloc[0]["commit_message"] == ""


class TestClusterCollection:
    """Integration tests for the full cluster_collection workflow."""

    @patch("app.vectordb.cluster_summaries.ChromaConfig")
    def test_end_to_end(self, mock_config_class):
        rng = np.random.RandomState(42)
        # Create 3 clear clusters of 20 points each in 10 dims
        centers = rng.randn(3, 10) * 10
        embeddings = []
        ids = []
        metadatas = []
        documents = []
        for ci, center in enumerate(centers):
            for j in range(20):
                embeddings.append((center + rng.randn(10) * 0.5).tolist())
                idx = ci * 20 + j
                ids.append(f"hash_{idx:03d}")
                metadatas.append({"repo_id": f"repo_{ci}", "commit_message": f"msg_{idx}"})
                documents.append(f"Summary for commit {idx}")

        mock_collection = Mock()
        mock_collection.get.return_value = {
            "ids": ids,
            "embeddings": embeddings,
            "metadatas": metadatas,
            "documents": documents,
        }
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection

        mock_config = Mock()
        mock_config.collection_name = "test_collection"
        mock_config.get_client.return_value = mock_client
        mock_config_class.return_value = mock_config

        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "clusters.parquet"
            df = cluster_collection(
                collection_name="test_collection",
                output_path=output,
                min_k=2,
                max_k=10,
            )

            assert len(df) == 60
            assert df["cluster_id"].nunique() == 3
            assert output.exists()

            # Read back and verify
            loaded = pd.read_parquet(output)
            assert len(loaded) == 60
            assert set(loaded.columns) == {
                "commit_hash",
                "cluster_id",
                "semantic_summary",
                "repo_id",
                "commit_message",
                "silhouette_sample_score",
                "embedding",
                "distance_to_centroid",
            }

    @patch("app.vectordb.cluster_summaries.ChromaConfig")
    def test_no_output_path_skips_write(self, mock_config_class):
        rng = np.random.RandomState(42)
        embeddings = (rng.randn(3, 10) * 10).tolist()
        for i in range(7):
            embeddings.append((np.array(embeddings[i % 3]) + rng.randn(10) * 0.5).tolist())

        mock_collection = Mock()
        mock_collection.get.return_value = {
            "ids": [f"h{i}" for i in range(10)],
            "embeddings": embeddings,
            "metadatas": [{"repo_id": "r", "commit_message": "m"}] * 10,
            "documents": [f"doc{i}" for i in range(10)],
        }
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection

        mock_config = Mock()
        mock_config.collection_name = "test"
        mock_config.get_client.return_value = mock_client
        mock_config_class.return_value = mock_config

        df = cluster_collection(collection_name="test", output_path=None)
        assert len(df) == 10
        assert "cluster_id" in df.columns
