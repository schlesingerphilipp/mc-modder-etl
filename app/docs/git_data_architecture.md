# Git Data Module Architecture

## Overview

The `git_data` module is responsible for extracting raw git commit data and GitHub Pull Request information from multiple Minecraft repositories. It performs the initial extraction and transformation phases of the ETL pipeline, producing intermediate Parquet files that feed into the summarization stage.

### Module Location
```
app/git_data/
├── etl_pipeline.py      # Main orchestration logic
├── extract_git_data.py  # Git repository cloning & commit extraction
├── extract_pr_data.py   # GitHub API PR extraction
└── models.py            # Pydantic data models
```

### Module Responsibilities
- Clone and cache git repositories locally
- Extract commit hashes, messages, and unified diffs using GitPython
- Fetch PR metadata via GitHub REST API
- Parse and match commits to PRs using hash prefix matching
- Split multi-file diffs into individual file components
- Generate unified ETL rows for downstream processing

---

## Data Structures (Pydantic Models)

Located in `app/git_data/models.py`:

### `Commit` Model
```python
class Commit(BaseModel):
    """Represents a git commit."""
    commit_hash: str = Field(..., description="Full commit SHA hash")
    message: str = Field(..., description="Commit message")
    diff: str = Field(default="", description="Unified diff output")
```

**Purpose:** Holds raw commit information extracted from Git repositories.

**Usage:** Created from dictionaries returned by `extract_git_data.extract_all_repos()`.

### `PR` Model
```python
class PR(BaseModel):
    """Represents a GitHub Pull Request."""
    id: int = Field(..., description="GitHub PR ID")
    title: str = Field(..., description="PR title")
    body: Optional[str] = Field(default=None, description="PR description/body")
    user: str = Field(..., description="GitHub username who created PR")
    created_at: str = Field(..., description="ISO timestamp of PR creation")
    merged_at: Optional[str] = Field(default=None, description="ISO timestamp of merge (None if not merged)")
```

**Purpose:** Holds GitHub PR metadata fetched via REST API.

**Usage:** Created from dictionaries returned by `extract_pr_data.extract_all_prs()`.

### `ETLRow` Model
```python
class ETLRow(BaseModel):
    """Represents a row in the final ETL output."""
    repo_id: str = Field(..., alias="Repo ID", description="Repository identifier (owner/repo")
    commit_hash: str = Field(..., alias="commit hash", description="Full commit SHA hash")
    commit_message: str = Field(..., alias="commit message", description="Commit message")
    diff: str = Field(..., description="Unified diff output")
    pr_message: Optional[str] = Field(default=None, alias="PR message", description="PR description (null if no PR)")
    pr_id: Optional[int] = Field(default=None, alias="PR ID", description="GitHub PR ID (null if no PR)")
    
    model_config = {"populate_by_name": True}  # Allow both alias and field name
```

**Purpose:** Final ETL output row that combines repository, commit, diff, and optional PR information. Each file in a commit's diff generates an `ETLRow`.

### `CommitSummary` Model
```python
class CommitSummary(BaseModel):
    """Represents a commit with its semantic summary."""
    commit_hash: str = Field(..., description="Full commit SHA hash")
    original_message: str = Field(..., description="Original commit message")
    semantic_summary: Optional[str] = Field(default=None, description="LLM-generated semantic summary of changes")
    status: str = Field(default="pending", description="Processing status: pending, completed, or failed")
    error_message: Optional[str] = Field(default=None, description="Error message if status is failed")
```

**Purpose:** Represents commits after summarization (used by `summarize` module).

---

## Entry Points and CLI Interfaces

### Poetry Script: `etl-pipeline`
Located in `app/git_data/etl_pipeline.py`, registered as the `etl-pipeline` command.

```python
def main():
    """Run the ETL pipeline to extract and combine commits, PRs, and diffs."""
    # 1. Extract commits from git repositories
    # 2. Extract PRs via GitHub API
    # 3. Match commits to PRs
    # 4. Split diffs by file
    # 5. Build ETL rows
    # 6. Write to Parquet (partitioned by Repo ID)

if __name__ == "__main__":
    main()
```

**Usage:**
```bash
poetry run etl-pipeline
# or after activating .venv:
etl-pipeline
```

**Output:** Writes partitioned Parquet to `/var/db/git_data` (or `DB_PATH` env var).

---

## Dependencies

### External Services
1. **GitPython** (`git.Repo`, `git.Repo.clone_from`)
   - Used for cloning repositories and extracting commit data
   - Provides diff output via `repo.git.diff(...)`

2. **GitHub REST API** (`requests.get`)
   - Endpoint: `https://api.github.com/repos/{owner/repo}/pulls?state=all`
   - Returns PR metadata (title, body, user, timestamps)
   - Does not require authentication for public repositories

### Standard Library Imports
- `os`, `re`, `typing`, `pandas` — Data handling and text processing
- `urllib.parse.quote` — URL encoding for Parquet partition paths

---

## Key Algorithms and Logic

### Repository Parsing (`parse_repo_id`)
```python
def parse_repo_id(repo_url: str) -> str:
    """Extract repository ID from URL like https://github.com/owner/repo"""
    parts = repo_url.rstrip("/").split("/")
    owner = parts[-2]
    repo = parts[-1]
    return f"{owner}/{repo}"
```

**Example:**
- Input: `"https://github.com/TheGreyGhost/MinecraftByExample"`
- Output: `"TheGreyGhost/MinecraftByExample"`

### Commit Hash Extraction (`extract_commit_hashes`)
```python
def extract_commit_hashes(text: str) -> set:
    """Extract 7-40 char hex strings from text (commit hash matching)."""
    pattern = r'\b[0-9a-f]{7,40}\b'
    return set(re.findall(pattern, text, re.IGNORECASE))
```

**Usage:** Matches commits to PRs by checking if commit hashes appear in PR messages.

### Commit-to-PR Matching (`match_commits_to_prs`)
```python
def match_commits_to_prs(commits: List[Commit], prs: List[PR]) -> Dict[str, Optional[PR]]:
    """Map commit hashes to PRs using hash prefix matching."""
    ```

**Matching Logic:**
1. Search for commit hashes within each PR's title and body text
2. If a hash found in PR matches the beginning of a commit's full hash, it's a match
3. First matching PR is preferred (map is `commit_hash -> PR or None`)

### Diff Splitting by File (`split_diff_by_file`)
```python
def split_diff_by_file(diff: str) -> List[str]:
    """Split multi-file unified diff into individual file diffs."""
    # Identifies boundaries using "diff --git" markers
    # Skips metadata lines (similarity, rename, index, mode markers)
    # Keeps ---, +++, @@ hunk headers, and actual changes
```

**Output:** List of strings, each containing the complete unified diff for one file. Empty commits result in a single empty string.

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    EXTRACT Phase                              │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              extract_git_data.py                      │   │
│  └──────────────────────────────────────────────────────┘   │
│                        │                                     │
│          GitPython.clone_from()                              │
│                        │                                     │
│        repo.git.diff("parent...HEAD")                        │
│                        │                                     │
│  outputs: commits_by_repo_url_raw                            │
│         {repo_url: [{"commit_hash": "...",                 │
│                      "message": "...",                      │
│                      "diff": "..."}, ...]}                  │
│                                                              │
└────────────────▼─────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   EXTRACT Phase                              │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              extract_pr_data.py                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                        │                                     │
│       GitHub API: GET /repos/{owner}/pulls?state=all         │
│                        │                                     │
│  outputs: prs_by_repo_id_raw                                 │
│         {repo_id: [{"id": 123,                             │
│                      "title": "...",                        │
│                      "body": "...",                         │
│                      "user": "..."}}, ...]}                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  TRANSFORM Phase                             │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           etl_pipeline.py (main orchestration)        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Steps:                                                      │
│    1. Convert raw dicts to Pydantic models                   │
│       commits_by_repo_url_raw → Dict[str, List[Commit]]      │
│       prs_by_repo_id_raw → Dict[str, List[PR]]               │
│                                                              │
│    2. For each repo:                                         │
│       - Parse repo URL → repo_id                             │
│       - Fetch PR list for this repo                          │
│       - Match commits to PRs                                  │
│       - Split each commit's diff by file                     │
│       - Build ETLRow for each file                           │
│                                                              │
│    3. Write output:                                           │
│       partitioned_parquet("Repo ID=...", "commit hash=...")   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                       │
                       ▼
                  Partitioned Parquet:
              DB_PATH/git_data/{Repo ID}/{commit hash}/...parquet
```

---

## Diff Truncation Limits

The `git_data` module handles diff data without truncation at this stage. Truncation occurs in the `summarize` module.

However, note the following behavior:
- Multi-file diffs are split but not truncated
- Empty diffs (for root commits) result in a single empty string row
- Diff sanitization is performed in `write_to_parquet()` to handle invalid UTF-8 characters that pyarrow rejects

---

## Module Interaction Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                            git_data/                                 │
│                                                                      │
│  ┌────────────────────┐     ┌────────────────────────────────────┐  │
│  │   extract_git_     │     │            models.py                │  │
│  │   data.py          │◄───►│  Pydantic Models:                  │  │
│  │                    │     │    - Commit                         │  │
│  └────────────────────┘     │    - PR                             │  │
│                            │    - ETLRow                          │  │
│                            │    - CommitSummary                   │  │
│        clone_repo()       │                                       │
│          extract_commit◄──┼──► populate_by_name=True              │
│        extract_all_repos  │     enables both aliases and fields   │
│                                                                      │
│  ┌────────────────────┐     ┌────────────────────────────────────┐  │
│  │   extract_pr_      │     │                                     │  │
│  │   data.py          │     │  Etalon:                            │  │
│  │                    │     │    "repo_id" field ←→ "Repo ID"     │  │
│  └────────────────────┘     │    alias for CSV output              │  │
│           get_prs()        │    Same pattern for other fields      │
│           extract_all◄──┼──►                                     │
│                              ^                                    │
│                              │ matches repo URL format to         │
│   GitHub API ───────────────┴───→ Repo URLs used in extract_      │
│                 (state=all, no pagination)                        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              etl_pipeline.py                                │   │
│  │                                                              │   │
│  │  Key Functions:                                             │   │
│  │    - parse_repo_id(repo_url) → repo_id                      │   │
│  │    - extract_commit_hashes(text) → set                      │   │
│  │    - match_commits_to_prs(commits, prs)                     │   │
│  │    - split_diff_by_file(diff) → List[str]                   │   │
│  │    - build_etl_rows(repo_url, commits, prs)                 │   │
│  │    - extract_and_transform()                                 │   │
│  │                                                              │   │
│  │  Main Entry Point: `etl-pipeline` CLI                       │   │
│  │                                                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Configuration

### Environment Variables (`.env`)
No environment variables required for `git_data` module operations.

The REPOS list in `extract_git_data.py` and `extract_pr_data.py` are hardcoded:

```python
REPOS = [
    "https://github.com/TheGreyGhost/MinecraftByExample",
    "https://github.com/TartaricAcid/TLMAdditionExample",
    "https://github.com/TartaricAcid/TouhouLittleMaid",
]
```

### Output Path
- Default: `/var/db/git_data`
- Override with `DB_PATH` environment variable

---

## CLI Entry Point Registration (pyproject.toml)

Registered as Poetry command in project root:
```toml
[tool.poetry.scripts]
etl-pipeline = "app.git_data.etl_pipeline:main"
```

---

## Testing Pattern

Located in `tests/git_data/`:
- Uses GitPython fixtures (mocked commit data)
- Tests for repository parsing, commit extraction logic
- Verifies PR matching algorithm with sample PRs

No LLM API keys required for tests.

