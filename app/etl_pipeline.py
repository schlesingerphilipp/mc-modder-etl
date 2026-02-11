import re
import csv
from typing import List, Dict, Any, Optional
from app.models import Commit, PR, ETLRow
from app.extract_git_data import extract_all_repos
from app.extract_pr_data import extract_all_prs


def split_diff_by_file(diff: str) -> List[str]:
    """
    Split a unified diff containing multiple files into individual file diffs.
    
    Uses unified diff format markers to identify file boundaries:
    - "--- a/filepath" and "+++ b/filepath" mark the start of each file's diff
    
    Args:
        diff: Complete unified diff string (possibly containing multiple files)
    
    Returns:
        List of individual file diffs. If diff is empty, returns empty list.
    """
    if not diff or not diff.strip():
        return []
    
    lines = diff.split('\n')
    file_diffs = []
    current_file_diff = []
    
    for i, line in enumerate(lines):
        # Check if this is a "--- a/" line (start of a file header)
        if line.startswith('--- a/'):
            # If we have accumulated lines from a previous file, save them
            if current_file_diff:
                file_diff_str = '\n'.join(current_file_diff).rstrip()
                if file_diff_str:
                    file_diffs.append(file_diff_str)
            # Start a new file with the "--- a/" line
            current_file_diff = [line]
        else:
            # Add all other lines to the current file
            current_file_diff.append(line)
    
    # Don't forget the last file's diff
    if current_file_diff:
        file_diff_str = '\n'.join(current_file_diff).rstrip()
        if file_diff_str:
            file_diffs.append(file_diff_str)
    
    return file_diffs


def parse_repo_id(repo_url: str) -> str:
    """
    Extract repository ID from a GitHub URL.
    
    Args:
        repo_url: Full GitHub URL (e.g., https://github.com/owner/repo)
    
    Returns:
        Repository ID in owner/repo format
    """
    # Remove trailing slash and split by /
    parts = repo_url.rstrip("/").split("/")
    owner = parts[-2]
    repo = parts[-1]
    return f"{owner}/{repo}"


def extract_commit_hashes(text: str) -> set:
    """
    Extract all commit hashes from text using regex.
    Matches 7-40 character hex strings (both short and full SHAs).
    
    Args:
        text: Text to search for commit hashes
    
    Returns:
        Set of commit hashes found
    """
    if not text:
        return set()
    # Match 7-40 character hexadecimal strings (commit hashes)
    pattern = r'\b[0-9a-f]{7,40}\b'
    return set(re.findall(pattern, text, re.IGNORECASE))


def match_commits_to_prs(
    commits: List[Commit], 
    prs: List[PR]
) -> Dict[str, Optional[PR]]:
    """
    Match commits to PRs by searching for commit hashes in PR body and title.
    Matches if any hash found in PR text is a prefix of the commit hash.
    
    Args:
        commits: List of Commit objects
        prs: List of PR objects
    
    Returns:
        Dictionary mapping commit_hash -> PR object (or None if no match)
    """
    commit_to_pr: Dict[str, Optional[PR]] = {}
    
    # Initialize all commits with None
    for commit in commits:
        commit_to_pr[commit.commit_hash] = None
    
    # Search for commit hashes in PR text
    for pr in prs:
        pr_text = ""
        if pr.title:
            pr_text += pr.title + " "
        if pr.body:
            pr_text += pr.body
        
        # Extract commit hashes from PR text
        hashes_in_pr = extract_commit_hashes(pr_text)
        
        # Match against commits
        for commit in commits:
            full_hash = commit.commit_hash
            
            # Check if any hash in PR is a prefix of this commit's hash
            for pr_hash in hashes_in_pr:
                if full_hash.startswith(pr_hash):
                    # Only map if not already mapped (first match wins)
                    if commit_to_pr[full_hash] is None:
                        commit_to_pr[full_hash] = pr
                    break
    
    return commit_to_pr


def build_etl_rows(
    repo_url: str,
    commits: List[Commit],
    prs: List[PR]
) -> List[ETLRow]:
    """
    Build ETL rows combining commits and PR data, splitting diffs by file.
    
    Each file in a commit's diff gets its own row with identical metadata
    (repo_id, commit_hash, commit_message, PR info) but different diff content.
    
    Args:
        repo_url: Full GitHub repository URL
        commits: List of Commit objects
        prs: List of PR objects
    
    Returns:
        List of ETLRow objects ready for output (may be larger than commits list
        if commits touch multiple files)
    """
    repo_id = parse_repo_id(repo_url)
    commit_to_pr = match_commits_to_prs(commits, prs)
    
    rows = []
    for commit in commits:
        commit_hash = commit.commit_hash
        pr = commit_to_pr.get(commit_hash)
        
        # Split the diff by file boundaries
        file_diffs = split_diff_by_file(commit.diff)
        
        # If no file diffs (empty diff or root commit), create one row with empty diff
        if not file_diffs:
            file_diffs = [""]
        
        # Create one row per file diff
        for file_diff in file_diffs:
            row = ETLRow(
                **{
                    "Repo ID": repo_id,
                    "commit hash": commit_hash,
                    "commit message": commit.message,
                    "diff": file_diff,
                    "PR message": pr.body if pr else None,
                    "PR ID": pr.id if pr else None,
                }
            )
            rows.append(row)
    
    return rows


def extract_and_transform() -> List[ETLRow]:
    """
    Orchestrate full ETL: extract commits and PRs, then transform into unified table.
    
    Returns:
        List of ETLRow objects ready for CSV output
    """
    # Extract commits by repo URL (raw dicts from extract_all_repos)
    commits_by_repo_url_raw = extract_all_repos()
    
    # Extract PRs by repo ID (raw dicts from extract_all_prs)
    prs_by_repo_id_raw = extract_all_prs()
    
    # Convert raw dicts to Pydantic models
    commits_by_repo_url: Dict[str, List[Commit]] = {
        repo_url: [Commit(**commit) for commit in commits]
        for repo_url, commits in commits_by_repo_url_raw.items()
    }
    
    prs_by_repo_id: Dict[str, List[PR]] = {
        repo_id: [PR(**pr) for pr in prs]
        for repo_id, prs in prs_by_repo_id_raw.items()
    }
    
    all_rows = []
    
    # Process each repository
    for repo_url, commits in commits_by_repo_url.items():
        repo_id = parse_repo_id(repo_url)
        prs = prs_by_repo_id.get(repo_id, [])
        
        rows = build_etl_rows(repo_url, commits, prs)
        all_rows.extend(rows)
    
    return all_rows


def write_to_csv(rows: List[ETLRow], output_file: str = "commits_prs_output.csv") -> None:
    """
    Write ETL rows to CSV file.
    
    Args:
        rows: List of ETLRow objects to write
        output_file: Output CSV filename
    """
    if not rows:
        print("No rows to write.")
        return
    
    fieldnames = ["Repo ID", "commit hash", "commit message", "diff", "PR message", "PR ID"]
    
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            # Convert ETLRow to dict using aliases
            row_dict = row.model_dump(by_alias=True)
            writer.writerow(row_dict)
    
    print(f"Wrote {len(rows)} rows to {output_file}")


def main():
    """Run the ETL pipeline to extract and combine commits, PRs, and diffs."""
    print("Starting ETL pipeline...")
    
    # Extract and transform data
    rows = extract_and_transform()
    print(f"Extracted and transformed {len(rows)} rows.")
    
    # Write to CSV
    write_to_csv(rows)
    print("ETL pipeline completed successfully!")