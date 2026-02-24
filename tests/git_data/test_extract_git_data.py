import tempfile
import os
import git
from unittest.mock import patch
from app.git_data.extract_git_data import clone_repo, extract_commit_data

TEST_REPO = "https://github.com/MockedRepo"

def mock_clone_from(repo_url, repo_path):
        os.makedirs(repo_path, exist_ok=True)
        # Write a dummy file to simulate a cloned repo
        with open(os.path.join(repo_path, "dummy.txt"), "w") as f:
                f.write("This is a dummy repository for testing.")
        # init the folder as a git repo
        repo = git.Repo.init(repo_path)
        # Create a dummy commit
        repo.index.add(["dummy.txt"])
        repo.index.commit("Initial commit")
        # Create a second file and commit
        with open(os.path.join(repo_path, "dummy2.txt"), "w") as f:
                f.write("This is another dummy file.")
        repo.index.add(["dummy2.txt"])
        repo.index.commit("Add second file")

def test_clone_repo(tmpdir):
        with patch("app.git_data.extract_git_data.git.Repo.clone_from", side_effect=mock_clone_from):
                repo_path = clone_repo(TEST_REPO, tmpdir)
                assert os.path.exists(repo_path)
                assert os.path.isdir(repo_path)

def test_extract_commit_data(tmpdir):
        with patch("app.git_data.extract_git_data.git.Repo.clone_from", side_effect=mock_clone_from):
                repo_path = clone_repo(TEST_REPO, tmpdir)
                commit_data = extract_commit_data(repo_path)
                assert isinstance(commit_data, list)
                assert len(commit_data) > 0
                for entry in commit_data:
                        assert "commit_hash" in entry
                        assert "message" in entry
                        assert "diff" in entry
