import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import csv

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from etl_pipeline import (
    parse_repo_id,
    extract_commit_hashes,
    match_commits_to_prs,
    build_etl_rows,
    write_to_csv,
)
from models import Commit, PR, ETLRow


class TestParseRepoId:
    """Test repository ID parsing from URLs."""
    
    def test_parse_full_github_url(self):
        """Test parsing full GitHub URL."""
        url = "https://github.com/TheGreyGhost/MinecraftByExample"
        assert parse_repo_id(url) == "TheGreyGhost/MinecraftByExample"
    
    def test_parse_url_with_trailing_slash(self):
        """Test parsing URL with trailing slash."""
        url = "https://github.com/TartaricAcid/TLMAdditionExample/"
        assert parse_repo_id(url) == "TartaricAcid/TLMAdditionExample"
    
    def test_parse_url_with_multiple_slashes(self):
        """Test parsing URL with trailing slashes."""
        url = "https://github.com/owner/repo///"
        assert parse_repo_id(url) == "owner/repo"


class TestExtractCommitHashes:
    """Test commit hash extraction from text."""
    
    def test_extract_full_sha(self):
        """Test extracting full 40-character SHA."""
        text = "Merged commit abc123def456abc123def456abc123def456"
        hashes = extract_commit_hashes(text)
        assert "abc123def456abc123def456abc123def456" in hashes
    
    def test_extract_short_sha(self):
        """Test extracting 7-character short SHA."""
        text = "Fixed in abc1234"
        hashes = extract_commit_hashes(text)
        assert "abc1234" in hashes
    
    def test_extract_multiple_hashes(self):
        """Test extracting multiple hashes."""
        text = "Merged abc1234 and def5678 commits"
        hashes = extract_commit_hashes(text)
        assert "abc1234" in hashes
        assert "def5678" in hashes
    
    def test_no_hashes_in_text(self):
        """Test when no hashes are present."""
        text = "This is a normal commit message"
        hashes = extract_commit_hashes(text)
        assert len(hashes) == 0
    
    def test_empty_text(self):
        """Test with empty text."""
        hashes = extract_commit_hashes("")
        assert len(hashes) == 0
    
    def test_none_text(self):
        """Test with None text."""
        hashes = extract_commit_hashes(None)
        assert len(hashes) == 0


class TestMatchCommitsToPRs:
    """Test commit-to-PR matching logic."""
    
    def test_match_by_short_hash(self):
        """Test matching commit to PR via short hash in PR body."""
        commits = [
            Commit(commit_hash="abc1234567890def1234567890def1234567890", message="Fix bug")
        ]
        prs = [
            PR(
                id=1,
                title="Bug fix",
                body="Fixes issue via commit abc12345",
                user="testuser",
                created_at="2026-02-11T00:00:00Z",
            )
        ]
        result = match_commits_to_prs(commits, prs)
        assert result["abc1234567890def1234567890def1234567890"] == prs[0]
    
    def test_match_by_full_hash(self):
        """Test matching commit to PR via full hash in PR body."""
        full_hash = "abc1234567890def1234567890def1234567890"
        commits = [Commit(commit_hash=full_hash, message="Fix bug")]
        prs = [
            PR(
                id=1,
                title="Bug fix",
                body=f"Merged in {full_hash}",
                user="testuser",
                created_at="2026-02-11T00:00:00Z",
            )
        ]
        result = match_commits_to_prs(commits, prs)
        assert result[full_hash] == prs[0]
    
    def test_no_match_returns_none(self):
        """Test that commits with no matching PR get None."""
        commits = [
            Commit(commit_hash="xyz9999999999999999999999999999999999", message="Feature")
        ]
        prs = [
            PR(
                id=1,
                title="Bug fix",
                body="Fixes via abc1234",
                user="testuser",
                created_at="2026-02-11T00:00:00Z",
            )
        ]
        result = match_commits_to_prs(commits, prs)
        assert result["xyz9999999999999999999999999999999999"] is None
    
    def test_multiple_commits_multiple_prs(self):
        """Test matching multiple commits to multiple PRs."""
        commits = [
            Commit(commit_hash="aaaa111111111111111111111111111111111111", message="Fix A"),
            Commit(commit_hash="bbbb222222222222222222222222222222222222", message="Fix B"),
        ]
        prs = [
            PR(id=1, title="PR1", body="Fixes aaaa111", user="user1", created_at="2026-02-11T00:00:00Z"),
            PR(id=2, title="PR2", body="Fixes bbbb222", user="user2", created_at="2026-02-11T00:00:00Z"),
        ]
        result = match_commits_to_prs(commits, prs)
        assert result["aaaa111111111111111111111111111111111111"].id == 1
        assert result["bbbb222222222222222222222222222222222222"].id == 2
    
    def test_pr_with_null_body(self):
        """Test PR with None body."""
        commits = [
            Commit(commit_hash="cccc333333333333333333333333333333333333", message="Fix C")
        ]
        prs = [
            PR(id=1, title="PR with no body", body=None, user="testuser", created_at="2026-02-11T00:00:00Z")
        ]
        result = match_commits_to_prs(commits, prs)
        assert result["cccc333333333333333333333333333333333333"] is None


class TestBuildETLRows:
    """Test ETL row building."""
    
    def test_build_rows_with_pr_match(self):
        """Test building rows when commits have matching PRs."""
        repo_url = "https://github.com/owner/repo"
        commits = [
            Commit(
                commit_hash="aaaa111111111111111111111111111111111111",
                message="Fix bug",
                diff="--- a/file.txt\n+++ b/file.txt",
            )
        ]
        prs = [
            PR(
                id=42,
                title="Bug fix PR",
                body="Fixes via commit aaaa111",
                user="testuser",
                created_at="2026-02-11T00:00:00Z",
            )
        ]
        
        rows = build_etl_rows(repo_url, commits, prs)
        assert len(rows) == 1
        assert rows[0].repo_id == "owner/repo"
        assert rows[0].commit_hash == "aaaa111111111111111111111111111111111111"
        assert rows[0].commit_message == "Fix bug"
        assert rows[0].diff == "--- a/file.txt\n+++ b/file.txt"
        assert rows[0].pr_message == "Fixes via commit aaaa111"
        assert rows[0].pr_id == 42
    
    def test_build_rows_without_pr_match(self):
        """Test building rows when commits have no matching PRs."""
        repo_url = "https://github.com/owner/repo"
        commits = [
            Commit(
                commit_hash="bbbb222222222222222222222222222222222222",
                message="Feature",
                diff="--- a/new.txt\n+++ b/new.txt",
            )
        ]
        prs = []
        
        rows = build_etl_rows(repo_url, commits, prs)
        assert len(rows) == 1
        assert rows[0].repo_id == "owner/repo"
        assert rows[0].commit_hash == "bbbb222222222222222222222222222222222222"
        assert rows[0].pr_message is None
        assert rows[0].pr_id is None
    
    def test_build_rows_mixed_matches(self):
        """Test building rows with some commits having PR matches and some not."""
        repo_url = "https://github.com/owner/repo"
        commits = [
            Commit(
                commit_hash="aaaa111111111111111111111111111111111111",
                message="Matched commit",
                diff="diff1",
            ),
            Commit(
                commit_hash="cccc333333333333333333333333333333333333",
                message="Unmatched commit",
                diff="diff2",
            ),
        ]
        prs = [
            PR(id=1, title="PR1", body="Fixes aaaa111", user="user1", created_at="2026-02-11T00:00:00Z")
        ]
        
        rows = build_etl_rows(repo_url, commits, prs)
        assert len(rows) == 2
        assert rows[0].pr_id == 1
        assert rows[1].pr_id is None


class TestWriteToCSV:
    """Test CSV output."""
    
    def test_write_csv_with_rows(self):
        """Test writing rows to CSV."""
        rows = [
            ETLRow(
                **{
                    "Repo ID": "owner/repo",
                    "commit hash": "abc123",
                    "commit message": "Fix bug",
                    "diff": "--- a/file.txt",
                    "PR message": "PR description",
                    "PR ID": 1,
                }
            ),
            ETLRow(
                **{
                    "Repo ID": "owner/repo",
                    "commit hash": "def456",
                    "commit message": "Feature",
                    "diff": "--- b/new.txt",
                    "PR message": None,
                    "PR ID": None,
                }
            ),
        ]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "test_output.csv")
            write_to_csv(rows, output_file)
            
            # Verify file exists and has correct content
            assert os.path.exists(output_file)
            
            with open(output_file, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                written_rows = list(reader)
            
            assert len(written_rows) == 2
            assert written_rows[0]["commit hash"] == "abc123"
            assert written_rows[0]["PR ID"] == "1"
            assert written_rows[1]["PR message"] == ""  # None becomes empty string in CSV
    
    def test_write_csv_empty_rows(self):
        """Test writing empty rows to CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "empty_output.csv")
            write_to_csv([], output_file)
            
            # File should not be created for empty rows
            assert not os.path.exists(output_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
