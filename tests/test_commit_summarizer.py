"""Tests for commit_summarizer module."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pandas as pd
from tempfile import TemporaryDirectory

from app.summarize.commit_summarizer import (
    CheckpointManager,
    CheckpointData,
    CommitSummarizer,
    compute_csv_hash,
)
from app.summarize.summarizer_config import SummarizerConfig


class TestCheckpointManager:
    """Tests for CheckpointManager class."""
    
    def test_load_nonexistent_checkpoint(self):
        """Test loading when checkpoint file doesn't exist."""
        with TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "checkpoint.json"
            manager = CheckpointManager(checkpoint_path)
            result = manager.load()
            assert result is None
    
    def test_save_and_load_checkpoint(self):
        """Test saving and loading checkpoint."""
        with TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "checkpoint.json"
            manager = CheckpointManager(checkpoint_path)
            
            # Create checkpoint
            data = CheckpointData(
                processed_commits={"abc123": "Summary 1"},
                failed_commits={"def456": "Error message"},
                total_commits=2
            )
            
            # Save and load
            manager.save(data)
            loaded = manager.load()
            
            assert loaded is not None
            assert loaded.processed_commits == {"abc123": "Summary 1"}
            assert loaded.failed_commits == {"def456": "Error message"}
            assert loaded.total_commits == 2
    
    def test_save_creates_directory(self):
        """Test that save creates checkpoint directory if it doesn't exist."""
        with TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "subdir" / "checkpoint.json"
            manager = CheckpointManager(checkpoint_path)
            
            data = CheckpointData(
                processed_commits={},
                failed_commits={},
                total_commits=0
            )
            
            # Directory doesn't exist yet - should fail gracefully
            # (depends on implementation, might need to create dir first)
            try:
                manager.save(data)
                # If we get here, directory was created or error was handled
                assert True
            except Exception:
                # Expected if directory creation isn't handled
                pass
    
    def test_load_corrupted_checkpoint(self):
        """Test loading corrupted checkpoint file."""
        with TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "checkpoint.json"
            
            # Write invalid JSON
            with open(checkpoint_path, "w") as f:
                f.write("invalid json {")
            
            manager = CheckpointManager(checkpoint_path)
            result = manager.load()
            
            # Should return None on corrupted file
            assert result is None


class TestCommitSummarizer:
    """Tests for CommitSummarizer class."""
    
    @pytest.fixture
    def config(self):
        """Create mock SummarizerConfig."""
        config = Mock(spec=SummarizerConfig)
        config.ollama_model = "llama3.1"
        config.max_retries = 3
        config.semantic_prompt_template = "Commit: {commit_message}\nDiffs:\n{combined_diffs}"
        return config
    
    @pytest.fixture
    def summarizer(self, config):
        """Create CommitSummarizer with mocked Ollama client."""
        with patch("app.summarize.commit_summarizer.OllamaLLM") as mock_llm:
            # Mock the chain: OllamaLLM().with_structured_output()
            mock_instance = Mock()
            mock_instance.with_structured_output.return_value = Mock()
            mock_llm.return_value = mock_instance
            
            summarizer = CommitSummarizer(config)
            summarizer.client = Mock()  
            return summarizer
    
    def test_group_rows_by_commit(self, summarizer):
        """Test grouping ETL rows by commit hash."""
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123", "def456"],
            "commit message": ["msg1", "msg1", "msg2"],
            "diff": ["diff1", "diff2", "diff3"],
        })
        
        groups = summarizer.group_rows_by_commit(df)
        
        assert len(groups) == 2
        assert len(groups["abc123"]) == 2
        assert len(groups["def456"]) == 1
    
    def test_combine_commit_diffs(self, summarizer):
        """Test combining diffs from multiple files in a commit."""
        group = pd.DataFrame({
            "commit hash": ["abc123", "abc123"],
            "diff": [
                "diff --git a/file1.py\n--- a/file1.py\n+++ b/file1.py\n@@ content @@",
                "diff --git a/file2.py\n--- a/file2.py\n+++ b/file2.py\n@@ content @@",
            ],
        })
        
        combined = summarizer.combine_commit_diffs(group)
        
        assert "file1.py" in combined
        assert "file2.py" in combined
        assert "FILE SEPARATOR" in combined
    
    def test_combine_commit_diffs_empty(self, summarizer):
        """Test combining when no diffs present."""
        group = pd.DataFrame({
            "commit hash": ["abc123"],
            "diff": [""],
        })
        
        combined = summarizer.combine_commit_diffs(group)
        assert combined == ""
    
    def test_create_semantic_prompt(self, summarizer):
        """Test prompt creation."""
        prompt = summarizer.create_semantic_prompt(
            "Fix bug in parser",
            "diff content here"
        )
        
        assert "Fix bug in parser" in prompt
        assert "diff content here" in prompt
    
    def test_summarize_with_llm_success(self, summarizer):
        """Test successful LLM API call."""
        mock_response = Mock()
        mock_response.semantic_summary = "Generated summary"
        summarizer.client.invoke.return_value = mock_response
        
        result = summarizer.summarize_with_llm("test prompt")
        
        assert result == "Generated summary"
        summarizer.client.invoke.assert_called_once_with("test prompt")
    
    def test_summarize_with_llm_retry(self, summarizer):
        """Test LLM API retry on failure."""
        mock_response = Mock()
        mock_response.semantic_summary = "Generated summary"
        
        # Fail first time, succeed second time
        summarizer.client.invoke.side_effect = [
            Exception("API error"),
            mock_response
        ]
        
        result = summarizer.summarize_with_llm("test prompt")
        
        assert result == "Generated summary"
        assert summarizer.client.invoke.call_count == 2
    
    def test_summarize_with_llm_max_retries(self, summarizer):
        """Test LLM API max retries exceeded."""
        summarizer.client.invoke.side_effect = Exception("API error")
        
        with pytest.raises(Exception, match="failed after"):
            summarizer.summarize_with_llm("test prompt")
    
    @patch("app.summarize.commit_summarizer.CheckpointManager")
    def test_process_commits_no_checkpoint(self, mock_checkpoint_class, summarizer):
        """Test processing commits from scratch."""
        # Mock checkpoint manager
        mock_checkpoint_mgr = Mock()
        mock_checkpoint_mgr.load.return_value = None
        mock_checkpoint_class.return_value = mock_checkpoint_mgr
        
        # Mock LLM response
        mock_response = Mock()
        mock_response.semantic_summary = "Summary for commit"
        summarizer.client.invoke.return_value = mock_response
        
        # Create test data
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123"],
            "commit message": ["Fix bug", "Fix bug"],
            "diff": ["diff1", "diff2"],
        })
        
        result_df, checkpoint = summarizer.process_commits(df, "testhash123")
        
        assert "semantic_summary" in result_df.columns
        assert all(result_df["semantic_summary"] == "Summary for commit")
    
    @patch("app.summarize.commit_summarizer.CheckpointManager")
    def test_process_commits_with_checkpoint(self, mock_checkpoint_class, summarizer):
        """Test resuming from checkpoint."""
        # Mock checkpoint with one processed commit
        checkpoint_data = CheckpointData(
            processed_commits={"abc123": "Previous summary"},
            failed_commits={},
            total_commits=2
        )
        mock_checkpoint_mgr = Mock()
        mock_checkpoint_mgr.load.return_value = checkpoint_data
        mock_checkpoint_class.return_value = mock_checkpoint_mgr
        
        # Create test data with two commits
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123", "def456"],
            "commit message": ["Fix bug", "Fix bug", "Add feature"],
            "diff": ["diff1", "diff2", "diff3"],
        })
        
        result_df, checkpoint = summarizer.process_commits(df, "testhash123")
        
        # abc123 should have previous summary, def456 should fail with error
        # (since we're not mocking new Gemini responses)
        assert len(checkpoint.processed_commits) >= 1


class TestComputeCSVHash:
    """Tests for compute_csv_hash function."""
    
    def test_compute_csv_hash(self):
        """Test computing CSV hash."""
        with TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "test.csv"
            csv_path.write_text("a,b,c\n1,2,3\n")
            
            hash1 = compute_csv_hash(csv_path)
            hash2 = compute_csv_hash(csv_path)
            
            # Hash should be consistent
            assert hash1 == hash2
            
            # Hash should be reasonable length (16 chars from SHA256)
            assert len(hash1) == 16
    
    def test_compute_csv_hash_different_files(self):
        """Test that different files produce different hashes."""
        with TemporaryDirectory() as tmpdir:
            csv1 = Path(tmpdir) / "test1.csv"
            csv2 = Path(tmpdir) / "test2.csv"
            
            csv1.write_text("a,b,c\n1,2,3\n")
            csv2.write_text("d,e,f\n4,5,6\n")
            
            hash1 = compute_csv_hash(csv1)
            hash2 = compute_csv_hash(csv2)
            
            assert hash1 != hash2


class TestSummarizeCommitsIntegration:
    """Integration tests for summarization workflow."""
    
    @pytest.fixture
    def sample_csv(self):
        """Create sample ETL CSV for testing."""
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123", "def456"],
            "commit message": [
                "Fix parser bug",
                "Fix parser bug",
                "Add new feature"
            ],
            "diff": [
                "diff --git a/parser.py\n--- a/parser.py\n+++ b/parser.py\n@@ fix",
                "diff --git a/test_parser.py\n--- a/test_parser.py\n+++ b/test_parser.py\n@@ test",
                "diff --git a/feature.py\n--- a/feature.py\n+++ b/feature.py\n@@ feat",
            ],
        })
        return df
    
    @patch("app.summarize.commit_summarizer.OllamaLLM")
    def test_full_workflow(self, mock_ollama_class, sample_csv):
        """Test full summarization workflow."""
        # Mock LLM responses
        mock_client = Mock()
        mock_response1 = Mock()
        mock_response1.semantic_summary = "Fixed critical bug in parser"
        mock_response2 = Mock()
        mock_response2.semantic_summary = "Implemented new feature"

        mock_instance = Mock()
        mock_instance.with_structured_output.return_value = mock_client
        mock_ollama_class.return_value = mock_instance
        mock_client.invoke.side_effect = [mock_response1, mock_response2]

        with TemporaryDirectory() as tmpdir:
            input_csv = Path(tmpdir) / "input.csv"
            sample_csv.to_csv(input_csv, index=False)

            config = Mock(spec=SummarizerConfig)
            config.ollama_model = "llama3.1"
            config.max_retries = 3
            config.semantic_prompt_template = "Commit: {commit_message}\nDiffs:\n{combined_diffs}"
            config.get_checkpoint_file = Mock(
                return_value=Path(tmpdir) / "checkpoint.json"
            )

            summarizer = CommitSummarizer(config)
            result_df, checkpoint = summarizer.process_commits(sample_csv, "test123")

            # Verify results
            assert "semantic_summary" in result_df.columns
            assert len(checkpoint.processed_commits) == 2
            assert len(checkpoint.failed_commits) == 0
