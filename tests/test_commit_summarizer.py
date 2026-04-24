"""Tests for commit_summarizer module."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd
from tempfile import TemporaryDirectory

from app.summarize.commit_summarizer import (
    CommitSummarizer,
    _extract_json_value,
)
from app.summarize.summarizer_config import SummarizerConfig


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
        config.max_synthesis_length = 10000
        config.file_summary_prompt_template = "File: {file_path}\nDiff:\n{diff}"
        config.commit_synthesis_prompt_template = "Commit: {commit_message}\nFiles:\n{file_summaries}"
        return config

    @pytest.fixture
    def summarizer(self, config):
        """Create CommitSummarizer with mocked LLM client."""
        with patch("app.summarize.commit_summarizer.ChatOpenAI") as mock_llm:
            mock_instance = Mock()
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
        mock_response.content = json.dumps({"file_summary": "Updated parser logic"})
        summarizer.file_client.invoke.return_value = mock_response

        result = summarizer.summarize_file_diff("parser.py", "diff content here")

        assert result == "Updated parser logic"
        summarizer.file_client.invoke.assert_called_once()

    def test_summarize_file_diff_retry(self, summarizer):
        """Test file diff summarization retry on failure."""
        mock_response = Mock()
        mock_response.content = json.dumps({"file_summary": "Updated parser logic"})

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
        mock_response.content = json.dumps({"semantic_summary": "Fixed critical parser bug"})
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

    def test_synthesize_commit_summary_chunking(self, summarizer):
        """Test chunked synthesis when file summaries exceed max_synthesis_length."""
        summarizer.config.max_synthesis_length = 200

        file_summaries = [
            {"file": f"src/module_{i}.py", "summary": f"Refactored module {i} to use new API pattern and updated all callers"}
            for i in range(20)
        ]

        mock_response = Mock()
        mock_response.content = json.dumps({"semantic_summary": "Combined summary"})
        summarizer.commit_client.invoke.return_value = mock_response

        result = summarizer.synthesize_commit_summary("Large refactor", file_summaries)

        assert result == "Combined summary"
        assert summarizer.commit_client.invoke.call_count > 1


class TestProcessCommits:
    """Tests for incremental parquet-based process_commits."""

    @pytest.fixture
    def config(self):
        config = Mock(spec=SummarizerConfig)
        config.lmstudio_model = "gpt-oss-20b"
        config.lmstudio_base_url = "http://host.docker.internal:1234/v1"
        config.lmstudio_api_key = "not-needed"
        config.max_retries = 3
        config.max_file_diff_length = 8000
        config.max_synthesis_length = 10000
        config.file_summary_prompt_template = "File: {file_path}\nDiff:\n{diff}"
        config.commit_synthesis_prompt_template = "Commit: {commit_message}\nFiles:\n{file_summaries}"
        return config

    @pytest.fixture
    def summarizer(self, config):
        with patch("app.summarize.commit_summarizer.ChatOpenAI") as mock_llm:
            mock_llm.return_value = Mock()
            summarizer = CommitSummarizer(config)
            return summarizer

    def _make_df(self):
        return pd.DataFrame({
            "Repo ID": ["owner/repo", "owner/repo", "owner/repo"],
            "commit hash": ["abc123", "abc123", "def456"],
            "commit message": ["Fix bug", "Fix bug", "Add feature"],
            "diff": ["diff1", "diff2", "diff3"],
            "PR message": [None, None, None],
            "PR ID": [None, None, None],
        })

    def test_process_commits_writes_parquet(self, summarizer):
        """Test that process_commits writes parquet partitions per commit."""
        mock_file_resp = Mock()
        mock_file_resp.content = json.dumps({"file_summary": "File summary"})
        summarizer.file_client.invoke.return_value = mock_file_resp

        mock_commit_resp = Mock()
        mock_commit_resp.content = json.dumps({"semantic_summary": "Commit summary"})
        summarizer.commit_client.invoke.return_value = mock_commit_resp

        df = self._make_df()

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "summaries"
            counts = summarizer.process_commits(df, output_dir)

            assert counts["processed"] == 2
            assert counts["skipped"] == 0
            assert counts["failed"] == 0

            result = pd.read_parquet(output_dir)
            assert len(result) == 2
            assert set(result["commit hash"]) == {"abc123", "def456"}
            assert all(result["semantic_summary"] == "Commit summary")

    def test_process_commits_skips_existing(self, summarizer):
        """Test that already-processed commits are skipped."""
        mock_file_resp = Mock()
        mock_file_resp.content = json.dumps({"file_summary": "File summary"})
        summarizer.file_client.invoke.return_value = mock_file_resp

        mock_commit_resp = Mock()
        mock_commit_resp.content = json.dumps({"semantic_summary": "Commit summary"})
        summarizer.commit_client.invoke.return_value = mock_commit_resp

        df = self._make_df()

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "summaries"

            # First run: processes everything
            counts1 = summarizer.process_commits(df, output_dir)
            assert counts1["processed"] == 2
            assert counts1["skipped"] == 0

            # Reset mock call counts
            summarizer.file_client.invoke.reset_mock()
            summarizer.commit_client.invoke.reset_mock()

            # Second run: everything should be skipped
            counts2 = summarizer.process_commits(df, output_dir)
            assert counts2["processed"] == 0
            assert counts2["skipped"] == 2

            # LLM should not have been called
            summarizer.file_client.invoke.assert_not_called()
            summarizer.commit_client.invoke.assert_not_called()

    def test_process_commits_empty_df(self, summarizer):
        """Test processing an empty DataFrame."""
        df = pd.DataFrame({
            "Repo ID": [],
            "commit hash": [],
            "commit message": [],
            "diff": [],
        })

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "summaries"
            counts = summarizer.process_commits(df, output_dir)

            assert counts["processed"] == 0
            assert counts["skipped"] == 0
            assert counts["failed"] == 0

    def test_file_checkpoint_resumes(self, summarizer):
        """Test that file-level checkpointing resumes within a commit."""
        df = pd.DataFrame({
            "Repo ID": ["owner/repo", "owner/repo"],
            "commit hash": ["abc123", "abc123"],
            "commit message": ["Fix bug", "Fix bug"],
            "diff": [
                "--- a/file1.py\n+++ b/file1.py\n@@ change1",
                "--- a/file2.py\n+++ b/file2.py\n@@ change2",
            ],
            "PR message": [None, None],
            "PR ID": [None, None],
        })

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "summaries"

            # Pre-create a file checkpoint with file1 already summarized
            cp_path = summarizer._file_checkpoint_path(output_dir, "owner/repo", "abc123")
            summarizer._save_file_checkpoint(cp_path, [
                {"file": "file1.py", "summary": "Previously saved summary for file1"}
            ])

            # Set up separate mocks for file and commit clients
            mock_file_resp = Mock()
            mock_file_resp.content = json.dumps({"file_summary": "Summary for file2"})
            file_mock = Mock()
            file_mock.invoke.return_value = mock_file_resp
            summarizer.file_client = file_mock

            mock_commit_resp = Mock()
            mock_commit_resp.content = json.dumps({"semantic_summary": "Combined summary"})
            commit_mock = Mock()
            commit_mock.invoke.return_value = mock_commit_resp
            summarizer.commit_client = commit_mock

            counts = summarizer.process_commits(df, output_dir)

            assert counts["processed"] == 1
            # file_client.invoke called only once (for file2, not file1)
            assert file_mock.invoke.call_count == 1
            # Checkpoint file should be cleaned up
            assert not cp_path.exists()

    def test_file_checkpoint_cleaned_up(self, summarizer):
        """Test that file checkpoint JSON is removed after successful parquet write."""
        df = pd.DataFrame({
            "Repo ID": ["owner/repo"],
            "commit hash": ["abc123"],
            "commit message": ["Fix bug"],
            "diff": ["--- a/file1.py\n+++ b/file1.py\n@@ change"],
            "PR message": [None],
            "PR ID": [None],
        })

        mock_file_resp = Mock()
        mock_file_resp.content = json.dumps({"file_summary": "Summary"})
        summarizer.file_client.invoke.return_value = mock_file_resp

        mock_commit_resp = Mock()
        mock_commit_resp.content = json.dumps({"semantic_summary": "Final"})
        summarizer.commit_client.invoke.return_value = mock_commit_resp

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "summaries"
            summarizer.process_commits(df, output_dir)

            # Parquet should exist
            result = pd.read_parquet(output_dir)
            assert len(result) == 1

            # No _file_summaries.json left behind
            checkpoints = list(output_dir.rglob("_file_summaries.json"))
            assert len(checkpoints) == 0


class TestSummarizeCommitsIntegration:
    """Integration tests for summarization workflow."""

    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame({
            "Repo ID": ["owner/repo", "owner/repo", "owner/repo"],
            "commit hash": ["abc123", "abc123", "def456"],
            "commit message": [
                "Fix parser bug", "Fix parser bug", "Add new feature"
            ],
            "diff": [
                "--- a/parser.py\n+++ b/parser.py\n@@ fix",
                "--- a/test_parser.py\n+++ b/test_parser.py\n@@ test",
                "--- a/feature.py\n+++ b/feature.py\n@@ feat",
            ],
            "PR message": [None, None, None],
            "PR ID": [None, None, None],
        })

    @patch("app.summarize.commit_summarizer.ChatOpenAI")
    def test_full_workflow(self, mock_openai_class, sample_df):
        """Test full summarization workflow with incremental parquet output."""
        mock_file_client = Mock()
        mock_commit_client = Mock()

        mock_file_response = Mock()
        mock_file_response.content = json.dumps({"file_summary": "File change description"})
        mock_file_client.invoke.return_value = mock_file_response

        mock_commit_response1 = Mock()
        mock_commit_response1.content = json.dumps({"semantic_summary": "Fixed critical bug in parser"})
        mock_commit_response2 = Mock()
        mock_commit_response2.content = json.dumps({"semantic_summary": "Implemented new feature"})
        mock_commit_client.invoke.side_effect = [mock_commit_response1, mock_commit_response2]

        mock_instance = Mock()
        mock_openai_class.return_value = mock_instance

        with TemporaryDirectory() as tmpdir:
            config = Mock(spec=SummarizerConfig)
            config.lmstudio_model = "gpt-oss-20b"
            config.lmstudio_base_url = "http://host.docker.internal:1234/v1"
            config.lmstudio_api_key = "not-needed"
            config.max_retries = 3
            config.max_file_diff_length = 8000
            config.max_synthesis_length = 10000
            config.file_summary_prompt_template = "File: {file_path}\nDiff:\n{diff}"
            config.commit_synthesis_prompt_template = "Commit: {commit_message}\nFiles:\n{file_summaries}"

            summarizer = CommitSummarizer(config)
            summarizer.file_client = mock_file_client
            summarizer.commit_client = mock_commit_client

            output_dir = Path(tmpdir) / "summaries"
            counts = summarizer.process_commits(sample_df, output_dir)

            assert counts["processed"] == 2
            assert counts["failed"] == 0

            result = pd.read_parquet(output_dir)
            assert len(result) == 2
            assert set(result["commit hash"]) == {"abc123", "def456"}


class TestExtractJsonValue:
    """Tests for _extract_json_value handling of malformed LLM responses."""

    def test_valid_json(self):
        content = '{"semantic_summary": "Fixed a bug"}'
        assert _extract_json_value(content, "semantic_summary") == "Fixed a bug"

    def test_truncated_json_missing_closing_brace(self):
        content = '{"semantic_summary": "Fixed a bug"'
        assert _extract_json_value(content, "semantic_summary") == "Fixed a bug"

    def test_truncated_json_missing_closing_quote_and_brace(self):
        content = '{"semantic_summary": "This commit addresses compatibility issues by switching the build dependency'
        result = _extract_json_value(content, "semantic_summary")
        assert "switching the build dependency" in result

    def test_markdown_code_fence(self):
        content = '```json\n{"file_summary": "Refactored module"}\n```'
        assert _extract_json_value(content, "file_summary") == "Refactored module"

    def test_markdown_code_fence_no_lang(self):
        content = '```\n{"file_summary": "Refactored module"}\n```'
        assert _extract_json_value(content, "file_summary") == "Refactored module"

    def test_escaped_quotes_in_value(self):
        content = r'{"semantic_summary": "Renamed \"old\" to \"new\""}'
        result = _extract_json_value(content, "semantic_summary")
        assert "old" in result and "new" in result

    def test_missing_key_raises(self):
        content = '{"wrong_key": "value"}'
        with pytest.raises(ValueError, match="Could not extract key"):
            _extract_json_value(content, "semantic_summary")

    def test_empty_content_raises(self):
        content = ""
        with pytest.raises(ValueError, match="Could not extract key"):
            _extract_json_value(content, "semantic_summary")

    def test_truncated_mid_sentence_file_summary(self):
        content = '{"file_summary": "Updated the parser to handle edge cases where the input is'
        result = _extract_json_value(content, "file_summary")
        assert "Updated the parser" in result

    def test_summarize_file_diff_with_truncated_response(self):
        """Integration: summarize_file_diff succeeds on first attempt with truncated JSON."""
        config = Mock(spec=SummarizerConfig)
        config.lmstudio_model = "gpt-oss-20b"
        config.lmstudio_base_url = "http://host.docker.internal:1234/v1"
        config.lmstudio_api_key = "not-needed"
        config.max_retries = 3
        config.max_file_diff_length = 8000
        config.file_summary_prompt_template = "File: {file_path}\nDiff:\n{diff}"

        with patch("app.summarize.commit_summarizer.ChatOpenAI"):
            summarizer = CommitSummarizer(config)

        mock_response = Mock()
        mock_response.content = '{"file_summary": "Updated build config to use standard slashblade'
        summarizer.file_client.invoke.return_value = mock_response

        result = summarizer.summarize_file_diff("build.gradle", "some diff")
        assert "Updated build config" in result
        # Should succeed on first call, no retries needed
        assert summarizer.file_client.invoke.call_count == 1

    def test_synthesis_with_truncated_response(self):
        """Integration: _invoke_synthesis succeeds on first attempt with truncated JSON."""
        config = Mock(spec=SummarizerConfig)
        config.lmstudio_model = "gpt-oss-20b"
        config.lmstudio_base_url = "http://host.docker.internal:1234/v1"
        config.lmstudio_api_key = "not-needed"
        config.max_retries = 3
        config.max_synthesis_length = 10000
        config.commit_synthesis_prompt_template = "Commit: {commit_message}\nFiles:\n{file_summaries}"

        with patch("app.summarize.commit_summarizer.ChatOpenAI"):
            summarizer = CommitSummarizer(config)

        mock_response = Mock()
        mock_response.content = (
            '{"semantic_summary": "This commit addresses compatibility issues by switching '
            "the build dependency from the 'slashblade-resharped' variant to the standard "
            "'slashblade' project and updating the corresp"
        )
        summarizer.commit_client.invoke.return_value = mock_response

        result = summarizer.synthesize_commit_summary(
            "Switch to standard slashblade",
            [{"file": "build.gradle", "summary": "Changed dependency"}],
        )
        assert "compatibility issues" in result
        assert summarizer.commit_client.invoke.call_count == 1
