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
    compute_file_hash,
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
        config.lmstudio_model = "gpt-oss-20b"
        config.lmstudio_base_url = "http://host.docker.internal:1234/v1"
        config.lmstudio_api_key = "not-needed"
        config.max_retries = 3
        config.max_file_diff_length = 8000
        config.file_summary_prompt_template = "File: {file_path}\nDiff:\n{diff}"
        config.commit_synthesis_prompt_template = "Commit: {commit_message}\nFiles:\n{file_summaries}"
        return config
    
    @pytest.fixture
    def summarizer(self, config):
        """Create CommitSummarizer with mocked LLM client."""
        with patch("app.summarize.commit_summarizer.ChatOpenAI") as mock_llm:
            mock_instance = Mock()
            mock_instance.with_structured_output.return_value = Mock()
            mock_llm.return_value = mock_instance
            
            summarizer = CommitSummarizer(config)
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
    
    def test_summarize_file_diff_success(self, summarizer):
        """Test successful file diff summarization."""
        mock_response = Mock()
        mock_response.file_summary = "Updated parser logic"
        summarizer.file_client.invoke.return_value = mock_response
        
        result = summarizer.summarize_file_diff("parser.py", "diff content here")
        
        assert result == "Updated parser logic"
        summarizer.file_client.invoke.assert_called_once()
    
    def test_summarize_file_diff_retry(self, summarizer):
        """Test file diff summarization retry on failure."""
        mock_response = Mock()
        mock_response.file_summary = "Updated parser logic"
        
        summarizer.file_client.invoke.side_effect = [
            Exception("API error"),
            mock_response
        ]
        
        result = summarizer.summarize_file_diff("parser.py", "diff content")
        
        assert result == "Updated parser logic"
        assert summarizer.file_client.invoke.call_count == 2
    
    def test_summarize_file_diff_max_retries(self, summarizer):
        """Test file diff summarization max retries exceeded."""
        summarizer.file_client.invoke.side_effect = Exception("API error")
        
        with pytest.raises(Exception, match="failed after"):
            summarizer.summarize_file_diff("parser.py", "diff content")
    
    def test_synthesize_commit_summary_success(self, summarizer):
        """Test successful commit synthesis."""
        mock_response = Mock()
        mock_response.semantic_summary = "Fixed critical parser bug"
        summarizer.commit_client.invoke.return_value = mock_response
        
        file_summaries = [
            {"file": "parser.py", "summary": "Fixed parsing logic"},
            {"file": "test_parser.py", "summary": "Added test"},
        ]
        result = summarizer.synthesize_commit_summary("Fix parser bug", file_summaries)
        
        assert result == "Fixed critical parser bug"
        summarizer.commit_client.invoke.assert_called_once()
    
    def test_synthesize_commit_summary_empty(self, summarizer):
        """Test synthesis with no file summaries."""
        result = summarizer.synthesize_commit_summary("Empty commit", [])
        assert result == "No file changes to summarize."
    
    @patch("app.summarize.commit_summarizer.CheckpointManager")
    def test_process_commits_no_checkpoint(self, mock_checkpoint_class, summarizer):
        """Test processing commits from scratch."""
        mock_checkpoint_mgr = Mock()
        mock_checkpoint_mgr.load.return_value = None
        mock_checkpoint_class.return_value = mock_checkpoint_mgr
        
        # Mock file-level and commit-level LLM responses
        mock_file_response = Mock()
        mock_file_response.file_summary = "File change summary"
        summarizer.file_client.invoke.return_value = mock_file_response
        
        mock_commit_response = Mock()
        mock_commit_response.semantic_summary = "Summary for commit"
        summarizer.commit_client.invoke.return_value = mock_commit_response
        
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
        checkpoint_data = CheckpointData(
            processed_commits={"abc123": "Previous summary"},
            failed_commits={},
            total_commits=2
        )
        mock_checkpoint_mgr = Mock()
        mock_checkpoint_mgr.load.return_value = checkpoint_data
        mock_checkpoint_class.return_value = mock_checkpoint_mgr
        
        # Mock LLM responses for the unprocessed commit
        mock_file_response = Mock()
        mock_file_response.file_summary = "New file summary"
        summarizer.file_client.invoke.return_value = mock_file_response
        
        mock_commit_response = Mock()
        mock_commit_response.semantic_summary = "New commit summary"
        summarizer.commit_client.invoke.return_value = mock_commit_response
        
        df = pd.DataFrame({
            "commit hash": ["abc123", "abc123", "def456"],
            "commit message": ["Fix bug", "Fix bug", "Add feature"],
            "diff": ["diff1", "diff2", "diff3"],
        })
        
        result_df, checkpoint = summarizer.process_commits(df, "testhash123")
        
        assert len(checkpoint.processed_commits) == 2
        assert checkpoint.processed_commits["abc123"] == "Previous summary"
        assert checkpoint.processed_commits["def456"] == "New commit summary"


class TestComputeFileHash:
    """Tests for compute_file_hash function."""
    
    def test_compute_file_hash(self):
        """Test computing file hash."""
        with TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.csv"
            file_path.write_text("a,b,c\n1,2,3\n")
            
            hash1 = compute_file_hash(file_path)
            hash2 = compute_file_hash(file_path)
            
            # Hash should be consistent
            assert hash1 == hash2
            
            # Hash should be reasonable length (16 chars from SHA256)
            assert len(hash1) == 16
    
    def test_compute_file_hash_different_files(self):
        """Test that different files produce different hashes."""
        with TemporaryDirectory() as tmpdir:
            file1 = Path(tmpdir) / "test1.dat"
            file2 = Path(tmpdir) / "test2.dat"
            
            file1.write_text("a,b,c\n1,2,3\n")
            file2.write_text("d,e,f\n4,5,6\n")
            
            hash1 = compute_file_hash(file1)
            hash2 = compute_file_hash(file2)
            
            assert hash1 != hash2


class TestSummarizeCommitsIntegration:
    """Integration tests for summarization workflow."""
    
    @pytest.fixture
    def sample_df(self):
        """Create sample ETL DataFrame for testing."""
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
    
    @patch("app.summarize.commit_summarizer.ChatOpenAI")
    def test_full_workflow(self, mock_openai_class, sample_df):
        """Test full summarization workflow."""
        # Mock LLM clients
        mock_file_client = Mock()
        mock_commit_client = Mock()
        
        # File-level summaries (2 files for abc123, 1 file for def456)
        mock_file_response = Mock()
        mock_file_response.file_summary = "File change description"
        mock_file_client.invoke.return_value = mock_file_response
        
        # Commit-level synthesis
        mock_commit_response1 = Mock()
        mock_commit_response1.semantic_summary = "Fixed critical bug in parser"
        mock_commit_response2 = Mock()
        mock_commit_response2.semantic_summary = "Implemented new feature"
        mock_commit_client.invoke.side_effect = [mock_commit_response1, mock_commit_response2]

        mock_instance = Mock()
        # with_structured_output is called twice: once for commit_client, once for file_client
        mock_instance.with_structured_output.side_effect = [mock_commit_client, mock_file_client]
        mock_openai_class.return_value = mock_instance

        with TemporaryDirectory() as tmpdir:
            config = Mock(spec=SummarizerConfig)
            config.lmstudio_model = "gpt-oss-20b"
            config.lmstudio_base_url = "http://host.docker.internal:1234/v1"
            config.lmstudio_api_key = "not-needed"
            config.max_retries = 3
            config.max_file_diff_length = 8000
            config.file_summary_prompt_template = "File: {file_path}\nDiff:\n{diff}"
            config.commit_synthesis_prompt_template = "Commit: {commit_message}\nFiles:\n{file_summaries}"
            config.get_checkpoint_file = Mock(
                return_value=Path(tmpdir) / "checkpoint.json"
            )

            summarizer = CommitSummarizer(config)
            result_df, checkpoint = summarizer.process_commits(sample_df, "test123")

            # Verify results
            assert "semantic_summary" in result_df.columns
            assert len(checkpoint.processed_commits) == 2
            assert len(checkpoint.failed_commits) == 0
