import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import csv

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from app.git_data.etl_pipeline import (
    parse_repo_id,
    extract_commit_hashes,
    match_commits_to_prs,
    build_etl_rows,
    write_to_csv,
    split_diff_by_file,
)
from app.git_data.models import Commit, PR, ETLRow


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


class TestSplitDiffByFile:
    """Test splitting diffs by file boundaries."""
    
    def test_split_single_file_diff(self):
        """Test splitting a diff with only one file."""
        diff = """--- a/file.txt
+++ b/file.txt
@@ -1,5 +1,6 @@
 line 1
-line 2
+line 2 modified
 line 3"""
        result = split_diff_by_file(diff)
        assert len(result) == 1
        assert "--- a/file.txt" in result[0]
        assert "+++ b/file.txt" in result[0]
    
    def test_split_multiple_files_diff(self):
        """Test splitting a diff with multiple files."""
        diff = """diff --git a/file1.txt b/file1.txt
index 1234567..abcdefg 100644
--- a/file1.txt
+++ b/file1.txt
@@ -1,3 +1,3 @@
 line 1
-line 2
+line 2 modified
diff --git a/file2.py b/file2.py
index 7654321..bcdefgh 100644
--- a/file2.py
+++ b/file2.py
@@ -10,5 +10,6 @@
 def foo():
     pass
-    return None
+    return True"""
        result = split_diff_by_file(diff)
        assert len(result) == 2
        assert "file1.txt" in result[0]
        assert "file2.py" in result[1]
        assert "file2.py" not in result[0]
        assert "file1.txt" not in result[1]
    
    def test_split_three_files_diff(self):
        """Test splitting a diff with three files."""
        diff = """diff --git a/src/main.py b/src/main.py
index 1111111..2222222 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1 @@
-old
+new
diff --git a/tests/test.py b/tests/test.py
index 3333333..4444444 100644
--- a/tests/test.py
+++ b/tests/test.py
@@ -1 +1 @@
-test old
+test new
diff --git a/README.md b/README.md
index 5555555..6666666 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-docs old
+docs new"""
        result = split_diff_by_file(diff)
        assert len(result) == 3
        assert "main.py" in result[0]
        assert "test.py" in result[1]
        assert "README.md" in result[2]
    
    def test_split_empty_diff(self):
        """Test splitting an empty diff."""
        result = split_diff_by_file("")
        assert result == []
    
    def test_split_none_diff(self):
        """Test splitting a None diff."""
        result = split_diff_by_file(None)
        assert result == []
    
    def test_split_whitespace_only_diff(self):
        """Test splitting a diff with only whitespace."""
        result = split_diff_by_file("   \n  \n  ")
        assert result == []
    
    def test_split_preserves_file_content(self):
        """Test that splitting preserves all file content correctly."""
        diff = """diff --git a/first.txt b/first.txt
index 9999999..aaaaaaa 100644
--- a/first.txt
+++ b/first.txt
@@ -1,2 +1,3 @@
 line 1
-line 2
+line 2a
+line 2b
diff --git a/second.txt b/second.txt
index bbbbbbb..ccccccc 100644
--- a/second.txt
+++ b/second.txt
@@ -5,3 +5,2 @@
 context
-removed
 more"""
        result = split_diff_by_file(diff)
        assert len(result) == 2
        # Check first file has its hunks
        assert "@@ -1,2 +1,3 @@" in result[0]
        assert "line 2a" in result[0]
        assert "line 2b" in result[0]
        # Check second file has its hunks
        assert "@@ -5,3 +5,2 @@" in result[1]
        assert "removed" in result[1]
    
    def test_split_with_git_metadata(self):
        """Test splitting with full git metadata (diff --git format with rename/index)."""
        diff = """diff --git a/src/file1.java b/src/file1.java
similarity index 53%
rename from src/old_file.java
rename to src/file1.java
index a8f78f5..af4cf7a 100644
--- a/src/old_file.java
+++ b/src/file1.java
@@ -2,5 +2,5 @@
 line 1
-old content
+new content
 line 3
diff --git a/src/file2.java b/src/file2.java
index 5bb25d6..9dae5b9 100644
--- a/src/file2.java
+++ b/src/file2.java
@@ -10,2 +10,3 @@
 context
+inserted
 more"""
        result = split_diff_by_file(diff)
        assert len(result) == 2
        # Verify metadata is dropped
        assert "similarity index" not in result[0]
        assert "rename from" not in result[0]
        assert "rename to" not in result[0]
        assert "index " not in result[0]
        assert "diff --git" not in result[0]
        # Verify actual diff content is preserved with file names
        assert "--- a/src/old_file.java" in result[0]
        assert "+++ b/src/file1.java" in result[0]
        assert "-old content" in result[0]
        assert "+new content" in result[0]
        # Check second file
        assert "--- a/src/file2.java" in result[1]
        assert "+++ b/src/file2.java" in result[1]
        assert "+inserted" in result[1]
    
    def test_split_with_resource_files(self):
        """Test splitting using real diff files from resources."""
        # Read the input diff
        with open(Path(__file__).parent / "resources" / "diff_example_input.txt", "r") as f:
            input_diff = f.read()
        
        # Read the expected output files
        with open(Path(__file__).parent / "resources" / "diff_example_output_1.txt", "r") as f:
            expected_output_1 = f.read()
        
        with open(Path(__file__).parent / "resources" / "diff_example_output_2.txt", "r") as f:
            expected_output_2 = f.read()
        
        # Split the diff
        result = split_diff_by_file(input_diff)
        
        # Verify we got 2 files
        assert len(result) == 2
        
        # Verify the content matches the expected outputs
        assert result[0] == expected_output_1
        assert result[1] == expected_output_2


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
    
    def test_build_rows_splits_multi_file_diff(self):
        """Test that diffs with multiple files are split into separate rows."""
        repo_url = "https://github.com/owner/repo"
        multi_file_diff = """diff --git a/file1.txt b/file1.txt
index 1234567..abcdefg 100644
--- a/file1.txt
+++ b/file1.txt
@@ -1,3 +1,3 @@
 line 1
-line 2
+line 2 modified
diff --git a/file2.py b/file2.py
index 7654321..bcdefgh 100644
--- a/file2.py
+++ b/file2.py
  line 010
  -line 011
  +line 011 modified
@@ -10,2 +10,3 @@
 def foo():
     pass
+    return True"""
        commits = [
            Commit(
                commit_hash="aaaa111111111111111111111111111111111111",
                message="Multi-file commit",
                diff=multi_file_diff,
            )
        ]
        prs = [
            PR(
                id=1,
                title="Multi-file PR",
                body="Fixes aaaa111",
                user="testuser",
                created_at="2026-02-11T00:00:00Z",
            )
        ]
        
        rows = build_etl_rows(repo_url, commits, prs)
        # Should create 2 rows (one per file)
        assert len(rows) == 2
        
        # Both rows should have the same metadata
        assert rows[0].repo_id == "owner/repo"
        assert rows[0].commit_hash == "aaaa111111111111111111111111111111111111"
        assert rows[0].commit_message == "Multi-file commit"
        assert rows[0].pr_id == 1
        
        assert rows[1].repo_id == "owner/repo"
        assert rows[1].commit_hash == "aaaa111111111111111111111111111111111111"
        assert rows[1].commit_message == "Multi-file commit"
        assert rows[1].pr_id == 1
        
        # But diffs should be different
        assert "file1.txt" in rows[0].diff
        assert "file2.py" in rows[1].diff
        assert "file2.py" not in rows[0].diff
        assert "file1.txt" not in rows[1].diff
        assert "line 1" in rows[0].diff
        assert "line 010" in rows[1].diff
        assert "line 1" not in rows[1].diff
        assert "line 010" not in rows[0].diff
    
    def test_build_rows_empty_diff_creates_one_row(self):
        """Test that commits with empty diffs still create a row."""
        repo_url = "https://github.com/owner/repo"
        commits = [
            Commit(
                commit_hash="root0000000000000000000000000000000000000",
                message="Root commit",
                diff="",
            )
        ]
        prs = []
        
        rows = build_etl_rows(repo_url, commits, prs)
        # Should create 1 row even with empty diff
        assert len(rows) == 1
        assert rows[0].diff == ""
    
    def test_build_rows_multiple_commits_with_varying_files(self):
        """Test multiple commits where some have single files and some have multiple."""
        repo_url = "https://github.com/owner/repo"
        commits = [
            Commit(
                commit_hash="aaaa111111111111111111111111111111111111",
                message="Single file commit",
                diff="diff --git a/file1.txt b/file1.txt\nindex 1111111..2222222 100644\n--- a/file1.txt\n+++ b/file1.txt\n@@ -1 +1 @@\n-old\n+new",
            ),
            Commit(
                commit_hash="bbbb222222222222222222222222222222222222",
                message="Two file commit",
                diff="""diff --git a/file2.txt b/file2.txt
index 3333333..4444444 100644
--- a/file2.txt
+++ b/file2.txt
@@ -1 +1 @@
-old2
+new2
diff --git a/file3.txt b/file3.txt
index 5555555..6666666 100644
--- a/file3.txt
+++ b/file3.txt
@@ -1 +1 @@
-old3
+new3""",
            ),
        ]
        prs = []
        
        rows = build_etl_rows(repo_url, commits, prs)
        # First commit: 1 row, second commit: 2 rows = 3 total
        assert len(rows) == 3
        assert rows[0].commit_hash == "aaaa111111111111111111111111111111111111"
        assert rows[1].commit_hash == "bbbb222222222222222222222222222222222222"
        assert rows[2].commit_hash == "bbbb222222222222222222222222222222222222"


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
