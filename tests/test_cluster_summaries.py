"""Tests for vectordb cluster_summaries module."""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory

from app.categorize.cluster_summaries import (
    fetch_embeddings,
    cluster_embeddings_hdbscan,
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



# HDBSCAN-based clustering tests
class TestClusterEmbeddingsHDBSCAN:
    def _make_clustered_data(self, n_per_cluster=30, n_clusters=3, dim=10):
        rng = np.random.RandomState(42)
        centers = rng.randn(n_clusters, dim) * 10
        data = []
        for center in centers:
            data.append(center + rng.randn(n_per_cluster, dim) * 0.5)
        return np.vstack(data)

    def test_hdbscan_finds_clusters(self):
        embeddings = self._make_clustered_data(n_per_cluster=30, n_clusters=3)
        labels = cluster_embeddings_hdbscan(embeddings, min_cluster_size=10)
        # Should find 3 clusters, some noise possible
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        assert n_clusters == 3
        assert labels.shape == (90,)

    def test_hdbscan_noise_points(self):
        # Make a small cluster that should be labeled as noise
        rng = np.random.RandomState(42)
        cluster = rng.randn(5, 10) * 10
        noise = rng.randn(20, 10) * 100
        embeddings = np.vstack([cluster, noise])
        labels = cluster_embeddings_hdbscan(embeddings, min_cluster_size=6)
        # All should be noise (-1)
        assert all(l == -1 for l in labels)

    def test_too_few_samples_raises(self):
        embeddings = np.array([[1.0, 2.0]])
        with pytest.raises(ValueError, match="at least 2"):
            cluster_embeddings_hdbscan(embeddings, min_cluster_size=2)





class TestBuildClusterDataframe:
    def test_output_columns_and_shape(self):
        ids = ["hash1", "hash2", "hash3"]
        labels = np.array([0, 1, -1])
        metadatas = [
            {"repo_id": "r1", "commit_message": "m1"},
            {"repo_id": "r1", "commit_message": "m2"},
            {"repo_id": "r2", "commit_message": "m3"},
        ]
        documents = ["summary 1", "summary 2", "summary 3"]
        embeddings = np.array([[0, 0], [10, 10], [100, 100]])

        df = build_cluster_dataframe(ids, labels, metadatas, documents, embeddings)

        assert len(df) == 3
        expected_cols = {
            "commit_hash",
            "cluster_id",
            "semantic_summary",
            "repo_id",
            "commit_message",
            "embedding",
            "distance_to_centroid",
        }
        assert set(df.columns) == expected_cols
        assert list(df["commit_hash"]) == ids
        assert list(df["cluster_id"]) == [0, 1, -1]
        assert all(isinstance(e, list) for e in df["embedding"])

    def test_handles_missing_metadata(self):
        ids = ["hash1", "hash2", "hash3"]
        labels = np.array([0, 1, -1])
        metadatas = [{}, {}, {}]
        documents = ["summary1", "summary2", "summary3"]
        embeddings = np.array([[0.0, 0.0], [10.0, 10.0], [100.0, 100.0]])

        df = build_cluster_dataframe(ids, labels, metadatas, documents, embeddings)

        assert df.iloc[0]["repo_id"] == ""
        assert df.iloc[0]["commit_message"] == ""


class TestClusterCollection:
    """Integration tests for the full cluster_collection workflow."""

    @patch("app.categorize.cluster_summaries.ChromaConfig")
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
                min_cluster_size=10,
            )

            assert len(df) == 60
            # Should find 3 clusters, some noise possible
            n_clusters = len(set(df["cluster_id"])) - (1 if -1 in set(df["cluster_id"]) else 0)
            assert n_clusters == 3
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
                "embedding",
                "distance_to_centroid",
            }

    @patch("app.categorize.cluster_summaries.ChromaConfig")
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
