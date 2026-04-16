import os
import tempfile
import git
from typing import List, Dict, Any

REPOS = [
    "https://github.com/TheGreyGhost/MinecraftByExample",
    "https://github.com/TartaricAcid/TLMAdditionExample",
    "https://github.com/TartaricAcid/TouhouLittleMaid",
]

def clone_repo(repo_url: str, clone_dir: str) -> str:
    repo_name = repo_url.rstrip("/").split("/")[-1]
    repo_path = os.path.join(clone_dir, repo_name)
    if not os.path.exists(repo_path):
        git.Repo.clone_from(repo_url, repo_path)
    return repo_path

def extract_commit_data(repo_path: str) -> List[Dict[str, Any]]:
    repo = git.Repo(repo_path)
    data = []
    for commit in repo.iter_commits():
        if commit.parents:
            # Use git command directly to get unified diff with file paths
            diff_text = repo.git.diff(f"{commit.parents[0].hexsha}...{commit.hexsha}")
        else:
            # For the first commit, show the diff against empty tree
            diff_text = repo.git.show(commit.hexsha)
        commit_info = {
            "commit_hash": commit.hexsha,
            "message": commit.message,
            "diff": diff_text,
        }
        data.append(commit_info)
    return data

def extract_all_repos() -> Dict[str, List[Dict[str, Any]]]:
    results = {}
    tmpdir = "/tmp/repos"
    for repo_url in REPOS:
        repo_path = clone_repo(repo_url, tmpdir)
        results[repo_url] = extract_commit_data(repo_path)
    return results

if __name__ == "__main__":
    all_data = extract_all_repos()
    print(f"Extracted data for {len(all_data)} repositories.")
