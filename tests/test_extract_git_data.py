import tempfile
import os
import pytest
from app.extract_git_data import clone_repo, extract_commit_data

TEST_REPO = "https://github.com/TheGreyGhost/MinecraftByExample"

def test_clone_repo(tmpdir):
        repo_path = clone_repo(TEST_REPO, tmpdir)
        assert os.path.exists(repo_path)
        assert os.path.isdir(repo_path)

def test_extract_commit_data(tmpdir):
        repo_path = clone_repo(TEST_REPO, tmpdir)
        commit_data = extract_commit_data(repo_path)
        assert isinstance(commit_data, list)
        assert len(commit_data) > 0
        for entry in commit_data:
            assert "commit_hash" in entry
            assert "message" in entry
            assert "diff" in entry
