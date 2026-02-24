#!/usr/bin/env python3
"""
Test script to demonstrate and validate the diff splitting functionality.
"""

from app.git_data.etl_pipeline import split_diff_by_file, build_etl_rows
from app.git_data.models import Commit, PR


def test_split_multi_file_diff():
    """Demonstrate splitting a multi-file diff."""
    print("=" * 70)
    print("TEST 1: Splitting a multi-file diff")
    print("=" * 70)
    
    sample_diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,3 @@
 def main():
-    print('old')
+    print('new')
--- a/src/utils.py
+++ b/src/utils.py
@@ -10,2 +10,3 @@
 def helper():
     pass
+    return True"""
    
    result = split_diff_by_file(sample_diff)
    print(f"\nInput: 1 diff with 2 files")
    print(f"Output: {len(result)} separate file diffs\n")
    
    for i, file_diff in enumerate(result, 1):
        print(f"--- File Diff {i} ---")
        print(file_diff)
        print()


def test_build_rows_with_splitting():
    """Demonstrate building ETL rows with automatic diff splitting."""
    print("=" * 70)
    print("TEST 2: Building ETL rows with multi-file diffs")
    print("=" * 70)
    
    repo_url = "https://github.com/example/project"
    
    # Create a commit with changes to 3 files
    multi_file_diff = """--- a/README.md
+++ b/README.md
@@ -1,2 +1,3 @@
 # Project
 Description
+More info
--- a/src/app.py
+++ b/src/app.py
@@ -5,3 +5,3 @@
 def run():
-    pass
+    start()
--- a/tests/test.py
+++ b/tests/test.py
@@ -1 +1,2 @@
 import app
+import pytest"""
    
    commits = [
        Commit(
            commit_hash="abc1234567890def1234567890def1234567890",
            message="Update documentation and implement features",
            diff=multi_file_diff,
        )
    ]
    
    prs = [
        PR(
            id=123,
            title="Feature implementation",
            body="Implements new features. Fixes abc12345",
            user="developer",
            created_at="2026-02-11T10:00:00Z",
        )
    ]
    
    rows = build_etl_rows(repo_url, commits, prs)
    
    print(f"\nInput: 1 commit with 3 files changed")
    print(f"Output: {len(rows)} ETL rows (1 per file)\n")
    
    for i, row in enumerate(rows, 1):
        print(f"Row {i}:")
        print(f"  Repo ID: {row.repo_id}")
        print(f"  Commit: {row.commit_hash[:8]}...")
        print(f"  PR ID: {row.pr_id}")
        print(f"  Message: {row.commit_message}")
        print(f"  Diff preview: {row.diff.split(chr(10))[0]}... ({len(row.diff)} chars)")
        print()


def test_single_file_unchanged():
    """Verify single-file commits still work correctly."""
    print("=" * 70)
    print("TEST 3: Single-file commits remain unchanged")
    print("=" * 70)
    
    repo_url = "https://github.com/example/project"
    
    single_file_diff = """--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,3 @@
 line 1
-line 2
+line 2 modified
 line 3"""
    
    commits = [
        Commit(
            commit_hash="def4567890abc1234567890abc1234567890abc1",
            message="Fix typo",
            diff=single_file_diff,
        )
    ]
    
    rows = build_etl_rows(repo_url, commits, [])
    
    print(f"\nInput: 1 commit with 1 file")
    print(f"Output: {len(rows)} ETL row\n")
    
    row = rows[0]
    print(f"Row 1:")
    print(f"  Repo ID: {row.repo_id}")
    print(f"  Commit: {row.commit_hash[:8]}...")
    print(f"  Message: {row.commit_message}")
    print(f"  Diff:\n{row.diff}")


def test_empty_diff():
    """Verify empty diffs are handled correctly."""
    print("\n" + "=" * 70)
    print("TEST 4: Empty diffs (root commits) still create one row")
    print("=" * 70)
    
    repo_url = "https://github.com/example/project"
    
    commits = [
        Commit(
            commit_hash="0000000000000000000000000000000000000000",
            message="Initial commit",
            diff="",
        )
    ]
    
    rows = build_etl_rows(repo_url, commits, [])
    
    print(f"\nInput: 1 commit with empty diff")
    print(f"Output: {len(rows)} ETL row\n")
    print(f"Row has empty diff: {rows[0].diff == ''}")


if __name__ == "__main__":
    test_split_multi_file_diff()
    test_build_rows_with_splitting()
    test_single_file_unchanged()
    test_empty_diff()
    
    print("\n" + "=" * 70)
    print("All manual tests completed successfully!")
    print("=" * 70)
