"""Tests for vectordb load_summaries module."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from tempfile import TemporaryDirectory

from app.vectordb.load_summaries import prepare_documents, load_summaries


def _fake_get_embeddings(texts, config):
    """Return deterministic fake embeddings for testing."""
    return [[0.1, 0.2, 0.3] for _ in texts]


class TestPrepareDocuments:
    """Tests for document preparation and deduplication."""

    def test_deduplicates_by_commit_hash(self):
        """Multiple rows per commit should collapse to one."""
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123", "def456"],
            "commit message": ["Fix bug", "Fix bug", "Add feature"],
            "semantic_summary": ["Summary A", "Summary A", "Summary B"],
        })
        result = prepare_documents(df)
        assert len(result) == 2
        assert set(result["commit hash"]) == {"abc123", "def456"}

    def test_skips_null_summaries(self):
        """Rows with null semantic_summary should be dropped."""
        df = pd.DataFrame({
            "commit hash": ["abc123", "def456"],
            "commit message": ["Fix", "Add"],
            "semantic_summary": ["Summary A", None],
        })
        result = prepare_documents(df)
        assert len(result) == 1
        assert result.iloc[0]["commit hash"] == "abc123"

    def test_skips_empty_summaries(self):
        """Rows with empty/whitespace semantic_summary should be dropped."""
        df = pd.DataFrame({
            "commit hash": ["abc123", "def456", "ghi789"],
            "commit message": ["Fix", "Add", "Remove"],
            "semantic_summary": ["Summary A", "", "   "],
        })
        result = prepare_documents(df)
        assert len(result) == 1
        assert result.iloc[0]["commit hash"] == "abc123"

    def test_keeps_valid_summary_when_duplicate_has_null(self):
        """If one row has null summary and another has valid, keep the valid one."""
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123"],
            "commit message": ["Fix bug", "Fix bug"],
            "semantic_summary": [None, "Valid summary"],
        })
        result = prepare_documents(df)
        assert len(result) == 1
        assert result.iloc[0]["semantic_summary"] == "Valid summary"

    def test_all_empty_returns_empty_df(self):
        """If all summaries are null/empty, return empty DataFrame."""
        df = pd.DataFrame({
            "commit hash": ["abc123"],
            "commit message": ["Fix"],
            "semantic_summary": [None],
        })
        result = prepare_documents(df)
        assert len(result) == 0

    def test_preserves_first_row_per_commit(self):
        """Dedup should keep the first occurrence."""
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123"],
            "commit message": ["First msg", "Second msg"],
            "semantic_summary": ["First summary", "Second summary"],
        })
        result = prepare_documents(df)
        assert len(result) == 1
        assert result.iloc[0]["commit message"] == "First msg"
        assert result.iloc[0]["semantic_summary"] == "First summary"


class TestLoadSummaries:
    """Tests for the load_summaries function."""

    def _write_test_parquet(self, tmpdir: str, df: pd.DataFrame) -> Path:
        path = Path(tmpdir) / "summaries.parquet"
        df.to_parquet(path, index=False)
        return path

    def test_file_not_found(self):
        """Should raise FileNotFoundError for missing input."""
        with pytest.raises(FileNotFoundError):
            load_summaries(Path("/nonexistent/file.parquet"))

    def test_missing_columns(self):
        """Should raise ValueError when required columns are missing."""
        with TemporaryDirectory() as tmpdir:
            df = pd.DataFrame({"commit hash": ["abc"], "other": ["x"]})
            path = self._write_test_parquet(tmpdir, df)
            with pytest.raises(ValueError, match="semantic_summary"):
                load_summaries(path)

    @patch("app.vectordb.load_summaries._get_embeddings", side_effect=_fake_get_embeddings)
    @patch("app.vectordb.load_summaries.ChromaConfig")
    def test_full_mode_drops_and_recreates(self, mock_config_class, mock_embed):
        """Full mode should drop existing collection and recreate it."""
        mock_collection = Mock()
        mock_client = Mock()
        mock_client.create_collection.return_value = mock_collection
        mock_config = Mock()
        mock_config.get_client.return_value = mock_client
        mock_config.collection_name = "test_collection"
        mock_config_class.return_value = mock_config

        with TemporaryDirectory() as tmpdir:
            df = pd.DataFrame({
                "Repo ID": ["owner/repo", "owner/repo", "owner/repo"],
                "commit hash": ["abc123", "abc123", "def456"],
                "commit message": ["Fix bug", "Fix bug", "Add feature"],
                "diff": ["diff1", "diff2", "diff3"],
                "PR message": ["PR desc", "PR desc", None],
                "PR ID": [1, 1, None],
                "semantic_summary": ["Summary A", "Summary A", "Summary B"],
            })
            path = self._write_test_parquet(tmpdir, df)
            count = load_summaries(path, collection_name="test_collection", mode="full")

        assert count == 2
        mock_client.delete_collection.assert_called_once_with(name="test_collection")
        mock_client.create_collection.assert_called_once_with(name="test_collection")
        mock_collection.upsert.assert_called_once()

        call_kwargs = mock_collection.upsert.call_args
        ids = call_kwargs.kwargs.get("ids") or call_kwargs[1].get("ids")
        documents = call_kwargs.kwargs.get("documents") or call_kwargs[1].get("documents")
        metadatas = call_kwargs.kwargs.get("metadatas") or call_kwargs[1].get("metadatas")

        assert set(ids) == {"abc123", "def456"}
        assert "Summary A" in documents
        assert "Summary B" in documents

        meta_by_id = {m["commit_hash"]: m for m in metadatas}
        assert meta_by_id["abc123"]["repo_id"] == "owner/repo"
        assert meta_by_id["abc123"]["pr_id"] == "1"
        assert "pr_message" not in meta_by_id["def456"]

        embeddings = call_kwargs.kwargs.get("embeddings") or call_kwargs[1].get("embeddings")
        assert len(embeddings) == 2
        assert all(isinstance(e, list) for e in embeddings)

    @patch("app.vectordb.load_summaries._get_embeddings", side_effect=_fake_get_embeddings)
    @patch("app.vectordb.load_summaries.ChromaConfig")
    def test_incremental_mode_skips_existing(self, mock_config_class, mock_embed):
        """Incremental mode should skip documents already in collection."""
        mock_collection = Mock()
        # abc123 already exists, def456 does not
        mock_collection.get.return_value = {"ids": ["abc123"]}
        mock_client = Mock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_config = Mock()
        mock_config.get_client.return_value = mock_client
        mock_config.collection_name = "test_collection"
        mock_config_class.return_value = mock_config

        with TemporaryDirectory() as tmpdir:
            df = pd.DataFrame({
                "commit hash": ["abc123", "def456"],
                "commit message": ["Fix bug", "Add feature"],
                "semantic_summary": ["Summary A", "Summary B"],
            })
            path = self._write_test_parquet(tmpdir, df)
            count = load_summaries(path, collection_name="test_collection", mode="incremental")

        assert count == 1
        mock_client.get_or_create_collection.assert_called_once()
        mock_client.delete_collection.assert_not_called()
        # Only def456 should be upserted
        call_kwargs = mock_collection.upsert.call_args
        ids = call_kwargs.kwargs.get("ids") or call_kwargs[1].get("ids")
        assert ids == ["def456"]

    @patch("app.vectordb.load_summaries.ChromaConfig")
    def test_incremental_mode_all_exist(self, mock_config_class):
        """Incremental mode should return 0 when all docs already exist."""
        mock_collection = Mock()
        mock_collection.get.return_value = {"ids": ["abc123", "def456"]}
        mock_client = Mock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_config = Mock()
        mock_config.get_client.return_value = mock_client
        mock_config.collection_name = "test_collection"
        mock_config_class.return_value = mock_config

        with TemporaryDirectory() as tmpdir:
            df = pd.DataFrame({
                "commit hash": ["abc123", "def456"],
                "commit message": ["Fix", "Add"],
                "semantic_summary": ["Summary A", "Summary B"],
            })
            path = self._write_test_parquet(tmpdir, df)
            count = load_summaries(path, collection_name="test_collection", mode="incremental")

        assert count == 0
        mock_collection.upsert.assert_not_called()

    @patch("app.vectordb.load_summaries.ChromaConfig")
    def test_returns_zero_for_all_empty_summaries(self, mock_config_class):
        """Should return 0 and not call ChromaDB when no valid docs."""
        with TemporaryDirectory() as tmpdir:
            df = pd.DataFrame({
                "commit hash": ["abc123"],
                "commit message": ["Fix"],
                "semantic_summary": [None],
            })
            path = self._write_test_parquet(tmpdir, df)
            count = load_summaries(path)

        assert count == 0
        mock_config_class.assert_not_called()

    @patch("app.vectordb.load_summaries._get_embeddings", side_effect=_fake_get_embeddings)
    @patch("app.vectordb.load_summaries.ChromaConfig")
    def test_batching(self, mock_config_class, mock_embed):
        """Should upsert in batches when doc count exceeds BATCH_SIZE."""
        mock_collection = Mock()
        mock_client = Mock()
        mock_client.create_collection.return_value = mock_collection
        mock_config = Mock()
        mock_config.get_client.return_value = mock_client
        mock_config.collection_name = "test_collection"
        mock_config_class.return_value = mock_config

        with TemporaryDirectory() as tmpdir:
            # Create 150 unique commits to force 2 batches
            n = 150
            df = pd.DataFrame({
                "commit hash": [f"hash_{i:04d}" for i in range(n)],
                "commit message": [f"msg_{i}" for i in range(n)],
                "semantic_summary": [f"summary_{i}" for i in range(n)],
            })
            path = self._write_test_parquet(tmpdir, df)
            count = load_summaries(path, collection_name="test_collection")

        assert count == 150
        assert mock_collection.upsert.call_count == 2  # 100 + 50
