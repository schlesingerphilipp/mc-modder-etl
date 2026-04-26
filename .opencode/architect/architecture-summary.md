# ETL Pipeline Architecture Summary

## System Overview

This document provides a comprehensive overview of the **Minecraft Commit Summarization System** — an end-to-end pipeline that extracts git commits and PR data from Minecraft repositories, generates semantic summaries using LLMs, and stores results in both Parquet files and ChromaDB vector database.

### Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                          MINECRAFT COMMIT SUMMARIZATION SYSTEM                        │
│                                                                                       │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐           │
│  │   Extract   │───▶│  Transform  │───▶│ Summarize   │───▶│   Storage   │           │
│  │             │    │ (ETL + Match)│   │ (LLM + Check)│   │              │           │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘           │
│            │             │               │                    │                      │
│            ▼             ▼               ▼                    ▼                      │
│  ┌──────────────────────────────────────────────────────────────────────────────┐   │
│  │                          External Services                                    │   │
│  │                                                                                │   │
│  │              ┌─────────────────┐       ┌───────────────────┐                 │   │
│  │              │  GitHub REST    │       │  LLM API (Gemini/ │                 │   │
│  │              │         API     │◄─────▶│ LMStudio/Gemini)  │                 │   │
│  │              │  PR Metadata    │       │                  │ │                 │   │
│  │              └─────────────────┘       └───────────────────┘ │                 │   │
│  │                                                            (1234/v1)          │   │
│  │                                                                                │   │
│  │                              ┌─────────────────┐                               │   │
│  │                              │  ChromaDB      │                               │   │
│  │                              │ Vector DB      │    (Semantic Search)           │   │
│  │                              └─────────────────┘                               │   │
│  └──────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                       │
│  CLI Entry Points:                                                                     │
│    • etl-pipeline     → Full extraction + transform (extract_and_transform())       │
│    • summarize-commits→ LLM semantic summarization (CLI interface)                  │
│    • run-notebook     → Execute Jupyter analysis notebooks                           │
│    • load-summaries   → Load summaries into ChromaDB                                │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Module Interaction Map (ASCII)

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                           END-TO-END SYSTEM ARCHITECTURE                                │
├─────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                         │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐ │
│  │                    EXTRACT PHASE                                                   │ │
│  │    ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │    │              app/git_data/extract_git_data.py                           │   │ │
│  │    │                                                                          │   │ │
│  │    │      Hardcoded Repository List:                                          │   │ │
│  │    │        • TheGreyGhost/MinecraftByExample                                 │   │ │
│  │    │        • TartaricAcid/TLMAdditionExample                                  │   │ │
│  │    │        • TartaricAcid/TouhouLittleMaid                                    │   │ │
│  │    │                                                                          │   │ │
│  │    │      Function: extract_all_repos() → Dict[repo_url, List[Dict]]          │   │ │
│  │    │                                                                          │   │ │
│  │    │      Process per repo:                                                   │   │ │
│  │    │        1. Clone via GitPython                                            │   │ │
│  │    │           git.Repo.clone_from(url, output_dir/owner/repo)               │   │ │
│  │    │                                                                          │   │ │
│  │    │        2. Iterate commits with iter_commits()                            │   │ │
│  │    │                                                                          │   │ │
│  │    │        3. Extract diff: repo.git.diff(parent...HEAD)                    │   │ │
│  │    │           - Root commit: repo.git.show(commit_hash)                      │   │ │
│  │    │                                                                          │   │ │
│  │    │      Return Structure:                                                   │   │ │
│  │    │        {                                                                 │   │ │
│  │    │          "https://github.com/owner/repo": [                             │   │ │
│  │    │            {                                                             │   │ │
│  │    │              "commit_hash": "...",                                       │   │ │
│  │    │              "message": "...",                                           │   │ │
│  │    │              "diff": "...[full unified diff...]"                        │   │ │
│  │    │            }, ...                                                        │   │ │
│  │    │          ]                                                               │   │ │
│  │    │        }                                                                 │   │ │
│  │    └────────────────────────────────────────────────────────┬─────────────────┘   │ │
│                                                                                         │ │
│  ┌──────────────────────────────────────────────────────────────▼─────────────────────┤ │
│  │                   EXTRACT PHASE (Parallel)                                         │ │
│  │    ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │    │              app/git_data/extract_pr_data.py                            │   │ │
│  │    │                                                                          │   │ │
│  │    │      Hardcoded Repository List:                                          │   │ │
│  │    │        • TheGreyGhost/MinecraftByExample                                 │   │ │
│  │    │        • TartaricAcid/TLMAdditionExample                                  │   │ │
│  │    │        • TartaricAcid/TouhouLittleMaid                                    │   │ │
│  │    │                                                                          │   │ │
│  │    │      Function: extract_all_prs() → Dict[repo_id, List[Dict]]            │   │ │
│  │    │                                                                          │   │ │
│  │    │      Process per repo (via owner/repo):                                  │   │ │
│  │    │        1. Construct GitHub API URL:                                      │   │ │
│  │    │           https://api.github.com/repos/{repo}/pulls?state=all           │   │ │
│  │    │                                                                          │   │ │
│  │    │        2. Fetch PR metadata (no auth needed for public repos):           │   │ │
│  │    │           requests.get(url).json()                                       │   │ │
│  │    │                                                                          │   │ │
│  │    │        3. Extract per-PR fields:                                         │   │ │
│  │    │           • id, title, body, user, created_at, merged_at                 │   │ │
│  │    │                                                                          │   │ │
│  │    │      Return Structure (Note key difference!):                            │   │ │
│  │    │        {                                                                 │   │ │
│  │    │          "TheGreyGhost/MinecraftByExample": [                           │   │ │
│  │    │            {                                                             │   │ │
│  │    │              "id": 123,                                                 │   │ │
│  │    │              "title": "...",                                             │   │ │
│  │    │              "body": "...",                                              │   │ │
│  │    │              "user": "...",                                              │   │ │
│  │    │              "created_at": "2024-01-01T...",                             │   │ │
│  │    │              "merged_at": "2024-01-05T... or null"                      │   │ │
│  │    │            }, ...                                                        │   │ │
│  │    │          ]                                                               │   │ │
│  │    │        }                                                                 │   │ │
│  │    │                                                                          │   │ │
│  │    └────────────────────────────────────────────────────────┬─────────────────┘   │ │
│                                                                                         │ │
│  ┌──────────────────────────────────────────────────────────────▼─────────────────────┤ │
│  │                    TRANSFORM PHASE                                                 │ │
│  │    ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │    │            app/git_data/etl_pipeline.py                                 │   │ │
│  │    │                                                                          │   │ │
│  │    │      Key Functions:                                                      │   │ │
│  │    │                                                                          │   │ │
│  │    │      1. parse_repo_id(repo_url) → repo_id                               │   │ │
│  │    │         "https://github.com/a/b" → "a/b"                                │   │ │
│  │    │                                                                          │   │ │
│  │    │      2. extract_commit_hashes(text, regex) → Set[str]                   │   │ │
│  │    │         Pattern: \b[0-9a-f]{7,40}\b                                     │   │ │
│  │    │                                                                          │   │ │
│  │    │      3. match_commits_to_prs(commits, prs) → Dict[hash, PR | None]      │   │ │
│  │    │         • Search commit hash prefixes in PR text                         │   │ │
│  │    │         • First-match-wins mapping                                      │   │ │
│  │    │                                                                          │   │ │
│  │    │      4. split_diff_by_file(diff) → List[str]                            │   │ │
│  │    │         • Parse multi-file unified diffs                                 │   │ │
│  │    │         • Identify boundaries via "diff --git" markers                  │   │ │
│  │    │         • Skip metadata lines (similarity, rename, mode indicators)      │   │ │
│  │    │                                                                          │   │ │
│  │    │      5. build_etl_rows(repo_url, commits, prs)                          │   │ │
│  │    │         Main transform logic:                                            │   │ │
│  │    │           a. Parse repo URL → repo_id                                    │   │ │
│  │    │           b. Fetch PR list for this repo                                 │   │ │
│  │    │           c. For each commit:                                            │   │ │
│  │    │              - Match to PR (if applicable)                               │   │ │
│  │    │              - Split diff by file boundaries                             │   │ │
│  │    │              - Create ETLRow per file                                    │   │ │
│  │    │                                                                          │   │ │
│  │    │        Return: List[ETLRow]                                              │   │ │
│  │    │         Each row has identical metadata but different diff content       │   │ │
│  │    │                                                                          │   │ │
│  │    │      Main Orchestration: extract_and_transform()                        │   │ │
│  │    │        1. Extract commits by repo URL                                    │   │ │
│  │    │        2. Extract PRs by repo ID                                         │   │ │
│  │    │        3. Convert raw dicts → Pydantic models                            │   │ │
│  │    │        4. For each repo in commits:                                      │   │ │
│  │    │           - Get matching PRs for this repo_id                           │   │ │
│  │    │           - Call build_etl_rows()                                       │   │ │
│  │    │           - Extend all_rows with results                                 │   │ │
│  │    │        5. Write to partitioned Parquet (see below)                       │   │ │
│  │    └────────────────────────────────────────────────────────┴─────────┬────────┘   │ │
│                                                                           │ │
│  ┌───────────────────────────────────────────────────────────────────────────┐     │ │
│  │                     PARQUET OUTPUT (Partitioned)                           │     │ │
│  │                                                                            │     │ │
│  │      Structure: {Repo ID} / {commit hash} / <filename>.parquet            │     │ │
│  │                                                                            │     │ │
│  │      Columns:                                                              │     │ │
│  │        • Repo ID          # Repository identifier (owner/repo)            │     │ │
│  │        • commit hash      # Full SHA hash                                 │     │ │
│  │        • commit message   # Original commit message                       │     │ │
│  │        • diff             # Unified diff content                          │     │ │
│  │        • PR message       # Optional: PR description (from body field)    │     │ │
│  │        • PR ID            # Optional: PR GitHub ID                        │     │ │
│  │                                                                            │     │ │
│  │      Partitioning Strategy:                                                │     │ │
│  │        - pyarrow automatically handles this                               │     │ │
│  │          when using partition_cols=["Repo ID", "commit hash"]             │     │ │
│  │        - Creates directories per partition                                 │     │ │
│  │                                                                            │     │ │
│  │      Note: CSV output uses space-separated column names                   │     │ │
│  │            ("commit hash" not "commit_hash") for downstream compatibility  │     │ │
│  └────────────────────────────────────────────────────────────────────────────┘     │ │
│                                                                                       │ │
│  ┌───────────────────────────────────────────────────────────────────────────────────┐ │
│  │                    SUMMARIZE PHASE (LLM Orchestration)                            │ │
│  │    ┌────────────────────────────────────────────────────────────────────────▾      │ │
│  │    │             app/summarize/summarizer_config.py                              │ │
│  │    │                                                                             │ │
│  │    │      Environment-Driven Configuration:                                      │ │
│  │    │        • LMSTUDIO_MODEL            = "gpt-oss-20b" (default)               │ │
│  │    │        • LMSTUDIO_BASE_URL         = "http://host.docker.internal:1234/v1" │ │
│  │    │        • LMSTUDIO_API_KEY          = "not-needed"                          │ │
│  │    │                                                                             │ │
│  │    │      Prompt Templates (file-based):                                         │ │
│  │    │        - PROMPT.md                     → Commit synthesis                   │ │
│  │    │        - FILE_SUMMARY_PROMPT.md        → File-level summary                  │ │
│  │    │        - COMMIT_SYNTHESIS_PROMPT.md    → Final commit synthesis              │ │
│  │    │                                                                             │ │
│  │    │      Limit Configuration:                                                   │ │
│  │    │        • max_retries                     = 3 (from MAX_* env)               │ │
│  │    │        • timeout_seconds                  = 60 (from TIMEOUT_SECONDS)        │ │
│  │    │        • max_diff_length                  = 15000 (truncation limit)        │ │
│  │    │        • max_file_diff_length             = 8000 (per-file cut-off)         │ │
│  │    │        • max_synthesis_length             = 8000 (chunking threshold)       │ │
│  │                                                                             │     │ │
│  │    └──────────────────────────┬───────────────────────────────────────────────┘   │ │
│                                  │                                                   │ │
│  ┌────────────────────────────────▼─────────────────────────────────────────────────┐ │
│  │             app/summarize/commit_summarizer.py (Core Logic)                       │ │
│  │                                                                                   │ │
│  │           Class: CommitSummarizer                                                 │ │
│  │     ┌─────────────────────────────────────────────────────────────────────────┐   │ │
│  │     │                    group_rows_by_commit(df)                              │   │ │
│  │     │      • Group ETL rows by "commit hash"                                   │   │ │
│  │     │      • Returns: {hash: DataFrame(group)}                                 │   │ │
│  │     └───────────────────────────────────┬─────────────────────────────────────┘   │ │
│                                           │                                         │ │
│  ┌─────────────────────────────────────────▼────────────────────────────────────────┐ │
│  │          PROCESS_COMMITS() - Main Orchestration Loop                             │ │
│  │                                                                                  │ │
│  │     For each commit_hash, comm_group in group_by_commit.items():                │ │
│  │       ├── Check if parquet partition exists                                      │ │
│  │       ├─ Skip if exists (counted in "skipped")                                  │ │
│  │       └─ Process if new:                                                         │ │
│  │           │                                                                     │   │
│  │           ▼                                                                    │   │ │
│  │       ┌────────────────────────────────────────────────────────────────────┐     │   │ │
│  │       │   File-Level Checkpointing (Per-File Progress Tracking)            │     │   │ │
│  │       │                                                                    │     │   │
│  │       │       For each file diff in commit:                                │     │   │ │
│  │       │         ├─ Extract file path:                                       │     │   │ │
│  │       │            - Scan diff for "--- a/path/to/file" or "+++ b/path/..." │     │   │ │
│  │       │            - Set to "unknown_{idx}" if not found                    │     │   │ │
│  │       │         ├─ Truncate if > MAX_FILE_DIFF_LENGTH (8000 default)        │     │   │ │
│  │       │         ├─ Format FILE_SUMMARY_PROMPT                               │     │   │ │
│  │       │         ├─ Invoke LLM via file_client.invoke(prompt)                │     │   │ │
│  │       │         ├─ Parse JSON response:                                     │     │   │ │
│  │       │              parsed = json.loads(content)['file_summary']           │     │   │ │
│  │       │         └─ Save to checkpoint:                                      │     │   │ │
│  │       │             [                              ]                        │     │   │ │
│  │       │              {"file": "src/main.py",      │     │   │ │
│  │       │              "summary": "..."}            │     │   │ │
│  │       │             ...                                                                   │     │   │ │
│  │       └────────────────────────────────┬─────────────────────────────────────┘     │ │
│                                           │                                         │ │
│  ┌─────────────────────────────────────────▼────────────────────────────────────────┐ │
│  │                   SYNTHESIS - Commit-Level Summary Generation                     │ │
│  │                                                                                  │ │
│  │       After all files summarized:                                                 │ │
│  │         ├─ Format file summaries with file paths and summaries                    │ │
│  │         ├─ Invoke COMMIT_SYNTHESIS_PROMPT                                        │ │
│  │         └─ Parse JSON response → semantic_summary                                │ │
│  │                                                                                  │ │
│  │       HIERARCHICAL CHUNKING (if exceeds MAX_SYNTHESIS_LENGTH):                     │ │
│  │         • Split formatted summaries into chunks ≤ max_synthesis_length              │ │
│  │         • Summarize each chunk independently                                       │ │
│  │         • Synthesize final summary from chunk summaries                            │ │
│  │                                                                                  │ │
│  └──────────────────────────────────┬─────────────────────────────────────────────────┘     │ │
│                                     │                                                    │ │
│  ┌───────────────────────────────────▼─────────────────────────────────────────────────┐   │ │
│  │                     WRITE TO PARTITIONED PARQUET                                    │   │ │
│  │                                                                                     │   │ │
│  │       Call: partitioned_parquet(output_dir, ...)                                   │   │ │
│  │       With columns:                                                                │   │ │
│  │         • Repo ID        # from row                                               │   │ │
│  │         • commit hash    # same as group key                                     │   │ │
│  │         • commit message # original commit                                         │   │ │
│  │         • PR message     # optional                                                │   │ │
│  │         • PR ID          # optional                                                │   │ │
│  │         • semantic_summary    # LLM output                                        │   │ │
│  │                                                                                     │   │ │
│  │       Delete temporary file checkpoint after successful write                       │   │ │
│  └───────────────────────────────────────────────────────────────────────────────────┘   │ │
│                                                                                           │ │
│  ┌─────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                      CLI ENTRY POINTS                                                │ │
│  ├─────────────────────────────────────────────────────────────────────────────────────┤ │
│  │                                                                                            │ │
│  │  Command                                          Description                         │ │
│  │  ─────────────────────────────────────────────────────────────────────────────────   │ │
│  │                                                                                       │ │
│  │  etl-pipeline                        Full ETL: extract commits + PRs → parquet output            │ │
│  │     • Runs extract_git_data.py + extract_pr_data.py                                       │ │
│  │     • Matches commits to PRs                                                              │ │
│  │     • Writes partitioned Parquet                                                          │ │
│  │                                                                                          │ │
│  │  summarize-commits                   LLM summarization from parquet input                 │ │
│  │     • Reads DB_PATH/git_data/                                                            │ │
│  │     • Generates semantic summaries                                                        │ │
│  │     • Writes to partitioned Parquet (new location)                                        │ │
│  │                                                                                          │ │
│  │  load-summaries                      Load summaries into ChromaDB vector database         │ │
│  │     • Reads partitioned parquet from output dir                                           │ │
│  │     • Supports full or incremental modes                                                  │ │
│  │     • Uses CHROMA_HOST, CHROMA_PORT, CHROMA_COLLECTION env vars                          │ │
│  │                                                                                          │ │
│  │  run-notebook                        Execute Jupyter notebooks programmatically            │ │
│  │     • Takes Python notebook file as argument                                             │ │
│  │     • Runs with nbconvert                       .ipynb                                   │ │
│  │     • Generates executed version as sidecar                                               │ │
│  │                                                                                            │ │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow Description

### End-to-End Data Flow

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL API INTEGRATIONS                                      │
├───────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                       │
│  ┌────────────────────────────────────────────────────────────────────────────────┐   │
│  │  External Service 1                   External Service 2                        │   │
│  │  ┌─────────────────────┐              ┌─────────────────────┐                  │   │
│  │  │ GitHub REST API     │◄───(HTTP)───►│ LLM APIs            │                  │   │
│  │  │                     │              │                      │                  │   │
│  │  │ Endpoints:          │              │ Supported Models:    │                  │   │
│  │  │ - GET /pulls        │              │ - gpt-oss-20b       │                  │   │
│  │  │   ?state=all        │              │ - gemini-1.5-pro    │                  │   │
│  │  │                     │              │ - Custom (OpenAI)    │                  │   │
│  │  │ Response:           │              │ BaseModel API        │                  │   │
│  │  │ {                   │              │                       │                  │   │
│  │  │   "id": 123,         │              │ Supported Endpoints:    │               │   │
│  │  │   "title": "...",    │              │ - LM Studio             │               │   │
│  │  │   "body": "...",     │              │   http://host.docker.internal:1234/v1   │              │   │
│  │  │   "user": "..."      │              │ - Google Gemini                 │           │   │
│  │  │   ...            │              │   (Google Cloud)                   │           │   │
│  │  │ }                  │              │   (requires GOOGLE_API_KEY env var)  │          │   │
│  │  └─────────────────────┘              └─────────────────────┘                  │   │
│  └────────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                       │
│  External Service 3: ChromaDB Vector Database                                        │
│    • Type: Apache Arrow-based vector database                                        │   │
│    • Used for: Semantic search, similarity retrieval                                 │   │
│    • Access: HTTP API (default endpoint)                                             │   │
│    ┌──────────────────────────────┐                                                  │
│    │ GET /api/v1/collections/{name}/get                      │                       │   │
│    │ POST /api/v1/collections/{name}/create                  │                       │   │
│    │ POST /api/v1/collections/{name}/upsert                  │                       │   │
│    │ DELETE /api/v1/collections/{name}/delete                │                       │   │
│    │                                                          │                       │   │
│    │ Default:                                                     │                       │
│    │ host: "chromadb" (Docker service name or hostname)         │                       │
│    │ port: 8000                                                 │                       │   │
│    └──────────────────────────────┘                                                  │
│                                                                                       │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Module Boundaries & Responsibilities

### git_data/ — Extract & Transform

| Component | Responsibility | Key Functions |
|-----------|----------------|---------------|
| `extract_git_data.py` | Clone repos, extract commits with diffs via GitPython | `clone_repo()`, `extract_commit_data()`, `extract_all_repos()` |
| `extract_pr_data.py` | Fetch PR metadata via GitHub REST API | `get_pr_messages()`, `extract_all_prs()` |
| `etl_pipeline.py` | Orchestrate extraction + matching + ETL row building | `match_commits_to_prs()`, `split_diff_by_file()`, `build_etl_rows()`, `extract_and_transform()` |
| `models.py` | Define Pydantic schemas and data models | `Commit`, `PR`, `ETLRow`, `CommitSummary` |

**Entry Point:** `etl-pipeline` CLI command  
**Output:** Partitioned Parquet at `{DB_PATH}/git_data/{owner/repo}/{commit_hash}/...parquet`

---

### summarize/ — LLM Summarization

| Component | Responsibility | Key Functions |
|-----------|----------------|---------------|
| `commit_summarizer.py` | Core summarization logic with checkpoint resume | `process_commits()`, `summarize_file_diff()`, `synthesize_commit_summary()` |
| `summarize_commits.py` | CLI entry point for summarization | `main()`, `validate_input()`, argparse config |
| `summarizer_config.py` | Environment-driven configuration and prompt loading | `SummarizerConfig.__init__()`, loads prompt .md files |
| PROMPT.md, FILE_SUMMARY_PROMPT.md, COMMIT_SYNTHESIS_PROMPT.md | Prompt template definitions | Jinja-style format strings for LLM calls |

**Entry Point:** `summarize-commits` CLI command  
**Input:** Partitioned Parquet from `git_data`  
**Output:** Partitioned Parquet with semantic summaries at `{output_dir}/{owner/repo}/{commit_hash}/...parquet`

---

### vectordb/ — Vector Database Integration

| Component | Responsibility | Key Functions |
|-----------|----------------|---------------|
| `load_summaries.py` | Load summaries into ChromaDB | `load_summaries()`, `_upsert_batches()`, `prepare_documents()` |
| `chroma_config.py` | ChromaDB connection configuration | `ChromaConfig.__init__()`, `get_client()` |

**Entry Point:** `load-summaries` CLI command  
**Input:** Partitioned Parquet with summaries  
**Output:** ChromaDB collection (`commit_summaries` by default)

---

### notebooks/ — Analysis Support

| Component | Responsibility | Key Functions |
|-----------|----------------|---------------|
| `run_notebook.py` | Execute Jupyter notebooks programmatically | `main()` (uses nbconvert's ExecutePreprocessor) |

**Entry Point:** `run-notebook` CLI command  
**Usage:** Run analysis notebooks on pipeline outputs

---

### utils/ — Shared Utilities

| Component | Responsibility | Key Functions |
|-----------|----------------|---------------|
| `logging.py` | Centralized logging configuration | `LOGGER` singleton, LOG_LEVEL environment var |

No entry points; support module only.

---

## Environment Variables Summary

```bash
# Git Data Module (no env vars required)
# • Uses hardcoded REPOS list

# Summarize Module
export LMSTUDIO_MODEL="gpt-oss-20b"              # LLM model name
export LMSTUDIO_BASE_URL="http://host.docker.internal:1234/v1"  # API endpoint
export LMSTUDIO_API_KEY="not-needed"              # For LM Studio (unused)
export MAX_RETRIES="3"                            # Retry attempts per call
export TIMEOUT_SECONDS="60"                       # Request timeout in seconds
export MAX_DIFF_LENGTH="15000"                    # Max total diff length
export MAX_FILE_DIFF_LENGTH="8000"                # Truncation: per-file limit
export MAX_SYNTHESIS_LENGTH="8000"                # Chunking threshold
export CHECKPOINT_DIR="./checkpoints"              # Checkpoint location
export LOG_LEVEL="INFO"                           # Logging level

# ChromaDB Module
export CHROMA_HOST="chromadb"                     # Host service name
export CHROMA_PORT="8000"                         # HTTP port
export CHROMA_COLLECTION="commit_summaries"       # Collection name

# General (Optional)
export DB_PATH="/var/db"                          # Override default output paths
```

---

## Diff Truncation & Limits Reference

| Stage | Limit | Environment Variable | Default Value | Purpose |
|-------|-------|---------------------|---------------|---------|
| File summarization input | 8,000 chars | `MAX_FILE_DIFF_LENGTH` | 8000 | Prevent LLM context overflow |
| Synthesis input | 8,000 chars | `MAX_SYNTHESIS_LENGTH` | 8000 | Triggers hierarchical chunking |
| Per-commit diff (not used) | 15,000 chars | `MAX_DIFF_LENGTH` | 15000 | Reserved for future use |

### Truncation Behavior

**When truncation occurs:**
```
Original File Diff: 12000 chars
└─ First 8000 chars preserved
└─ Remaining discarded
└─ Marker added: "\n\n[... DIFF TRUNCATED ...]" → LLM aware of truncation
```

### Chunking Behavior

**When chunking is triggered:**
```
1. Format all file summaries into lines
2. If total > MAX_SYNTHESIS_LENGTH (8000):
   ├─ Split into chunks fitting within limit
   ├─ Summarize each chunk independently
   └─ Synthesize final summary from chunk summaries
```

---

## Checkpoint/Resume Patterns

### Two-Level Resume Strategy

1. **Per-Commit Resume:**
   - Check if partition exists at output path
   - Skip entire commit if already processed (fast failure)

2. **Per-File Resume:**
   - Save checkpoint after each file is summarized
   - Location: `{output_dir}/Repo ID={X}/commit hash={Y}/_file_summaries.json`
   - Resume on partial processing of new commits
   - Delete checkpoint after successful commit write

### Checkpoint Contents

```json
[
  {
    "file": "src/main.py",
    "summary": "Added user authentication with JWT token validation"
  },
  {
    "file": "README.md",
    "summary": "Updated documentation with installation instructions"
  }
]
```

### Resume Command Pattern

```bash
# Interrupted run: resume from checkpoint on restart
poetry run summarize-commits /var/db/git_data/ /var/db/summaries

# Output shows:
# "Resuming file summaries: 12 already done"
# Continues where it left off
```

---

## API Integrations Reference

### GitHub REST API

**Endpoint:** `https://api.github.com/repos/{owner/repo}/pulls?state=all`  
**Method:** GET  
**Authentication:** None (public repos)  

**Sample Response:**
```json
[
  {
    "id": 123,
    "title": "Add logging utility",
    "body": "This PR introduces logging utilities...",
    "user": {"login": "contributor"},
    "created_at": "2024-03-15T10:30:00Z",
    "merged_at": "2024-03-20T14:00:00Z"
  }
]
```

**Mapping to Pydantic Model:**
```python
class PR(BaseModel):
    id: int = Field(..., description="GitHub PR ID")
    title: str = Field(..., description="PR title")
    body: Optional[str] = Field(default=None, description="PR description/body")
    user: str = Field(..., description="GitHub username who created PR")
    created_at: str = Field(..., description="ISO timestamp of PR creation")
    merged_at: Optional[str] = Field(
        default=None, description="ISO timestamp of merge (None if not merged)"
    )
```

---

### LLM APIs (LangChain)

**Supported Models:**
1. **Google Gemini** (`ChatOpenAI` with Google API key)
2. **LM Studio** (localhost inference via Docker)
3. **Any OpenAI-compatible API** (custom deployment)

**Configuration:**
```python
from langchain_openai import ChatOpenAI

client = ChatOpenAI(
    model=config.lmstudio_model,  # e.g., "gpt-oss-20b"
    base_url=config.lmstudio_base_url,  # e.g., "http://host.docker.internal:1234/v1"
    api_key=config.lmstudio_api_key,  # e.g., "not-needed" for LM Studio
    temperature=0  # Zero temperature for reproducible outputs
)
```

**Response Parsing:**
- Expects JSON response matching prompt schema
- Key fields: `file_summary` (for file summaries), `semantic_summary` (for commit synthesis)
- Validation: Empty content → ValueError, Parse errors → exception chain

---

## Configuration Files & Prompt Templates

### Located in: `app/summarize/`

| File | Purpose | Variables Used |
|------|---------|----------------|
| `PROMPT.md` | Commit synthesis prompt template | `{commit_message}`, `{combined_diffs}` (for full) or per-file summaries |
| `FILE_SUMMARY_PROMPT.md` | File-level summary prompt | `{file_path}`, `{diff}` |
| `COMMIT_SYNTHESIS_PROMPT.md` | Commit synthesis prompt | `{commit_message}`, `{file_summaries}` |

### Prompt Format Structure

```markdown
# COMMIT_SYNTHESIS_PROMPT
Based on the following per-file summaries, create a concise 2-3 sentence semantic summary of this entire commit focusing on:
1. What problem or issue was solved
2. What code patterns or logic changed
3. The business or functional impact

Commit Message: {commit_message}

File Summaries:
{file_summaries}

Respond with ONLY a JSON object in this exact format (no other text):
{{"semantic_summary": "your summary here"}}
```

---

## Testing Strategy

### Test Locations

- `tests/git_data/` — Tests for extract_git_data.py, extract_pr_data.py, etl_pipeline.py
- `tests/git_data/resources/` — Fixture data (mock commits, PRs)
- `tests/summarize/test_commit_summarizer.py` — Summarizer logic tests with mocked LLM calls

### Mocked Testing Principles

1. **No Real API Calls:** All tests use mocked responses
2. **GitPython Operations Mocked:** No actual repository cloning in tests
3. **LLM Responses Mocked:** Expected JSON formats for validation
4. **Checkpoint System Tested:** Save, load, resume patterns verified independently

### Example Test Pattern (Commit Summarizer)

```python
class TestCommitSummarizer:
    
    @pytest.mark.asyncio
    async def test_process_commits_respects_checkpoint_resume(self):
        """Test that processing resumes from checkpoint correctly."""
        
        # Setup mock LLM response
        mock_file_response = FileSummaryResult(
            file_summary="Added feature X"
        )
        
        mock_commit_response = CommitSummaryResult(
            semantic_summary="This commit adds feature X to Y."
        )
        
        # Test checkpoint load/save cycle
        with patch.object(commit_summarizer.FileClient, "invoke", lambda self, x: mock_file_response):
            result_counts = await commit_summarizer.process_commits(df=mock_etl_data, output_dir=mock_output)
            
            assert result_counts["processed"] > 0
            
        # Verify checkpoint directory structure
        checkpoint_dir = Path(output_dir) / "Repo ID=test" / "commit hash=abc123..."
        assertion: checkpoint_dir / ".file_summaries.json" exists()
```

---

## CLI Usage Summary

### All Entry Points at a Glance

| Command | Module File | Default Input | Default Output | Description |
|---------|-------------|----------------|----------------|-------------|
| `etl-pipeline` | `app/git_data/etl_pipeline.py::main()` | N/A (hardcoded repos) | `/var/db/git_data` | Extract commits+PRs, write intermediate Parquet |
| `summarize-commits` | `app/summarize/summarize_commits.py::main()` | `/var/db/git_data/` | `/var/db/summaries` | Generate LLM summaries from ETL output |
| `load-summaries` | `app/vectordb/load_summaries.py::main()` | `{DB_PATH}/summaries` | ChromaDB collection: `commit_summaries` | Load into vector database |
| `run-notebook` | `app/notebooks/run_notebook.py::main()` | N/A (positional arg) | `<input>.py_executed.ipynb` | Execute analysis notebook |

### Example Workflow Commands

```bash
# 1. Run full ETL pipeline
poetry run etl-pipeline

# 2. Summarize commits from current ETL output
poetry run summarize-commits /var/db/git_data/ /var/db/summaries

# 3. Load summaries into ChromaDB (full reset)
poetry run load-summaries /var/db/summaries --mode full

# 4. Incremental update to vector DB
poetry run load-summaries /var/db/summaries --mode incremental --collection my_custom_name

# 5. Run analysis notebook
poetry run run-notebook app/notebooks/summary_analysis.py
```

---

## Design Patterns & Conventions

### Python >=3.11 with Poetry
- Strict typing throughout
- Pydantic models for all structured data
- Type hints on function parameters and returns

### Partitioned Parquet I/O
- Uses PyArrow's `partition_cols` feature
- Creates directory structure per partition
- Enables efficient filtering by repo/commit without reading full file

### Space-Separated CSV Columns
- `"Repo ID"` not `"repo_id"` for user-facing files
- `"commit hash"` not `"commit_hash"` 
- Matches column names expected in downstream analysis
- Pydantic models use both field names and aliases with `populate_by_name=True`

### LLM Response Parsing Pattern
```python
try:
    response = client.invoke(prompt)
    content = response.content.strip()
    
    # Validate non-empty
    if not content:
        raise ValueError("LLM returned empty content")
    
    # Parse JSON
    parsed = json.loads(content)
    return parsed["field_name"]
except Exception as e:
    last_error = e
    if attempt < max_retries - 1:
        LOGGER.warning(f"Attempt failed, retrying: {e}")
    else:
        raise Exception("Failed after retries") from last_error
```

### Diff Limit Handling Pattern
```python
truncated = False
orig_length = len(diff)
if len(diff) > config.max_file_diff_length:
    diff = diff[:config.max_file_diff_length]
    truncated = True
    LOGGER.warning(f"Diff truncated from {orig_length} to {max_length}")
    
    # Add truncation marker for LLM awareness
    if truncated:
        diff_for_prompt = diff + "\n\n[... DIFF TRUNCATED ...]"
```

### Checkpoint Pattern (Incremental Write)
- Writes immediately after processing each unit (file or commit partition)
- Deletes temporary checkpoints upon success
- Allows graceful restart without reprocessing completed work

---

## Future Enhancements & Known Limitations

### Current System Behavior

- **One-to-one matching:** Each commit can match at most one PR (first-match-wins in parsing)
- **Root commits handled separately:** Commits with no parents use `git show()` for diff
- **Empty diffs result in empty rows:** Not filtered out at ETL stage

### Enhancement Possibilities

1. **Multi-file summary merging:** Current synthesizer is hierarchical, could be improved further
2. **Embedding generation:** Currently raw text loaded into ChromaDB; embedding models could improve semantic search
3. **Prompt versioning:** Prompts stored in files; central version registry would help track changes
4. **Metadata enrichment:** PR metadata includes GitHub-specific fields (assignees, reviewers, labels) not yet utilized
5. **Error handling enhancements:** More robust JSON parsing for LLM edge cases

---

## Quick Reference: File to Function Mapping

| File | Contains | Type |
|------|----------|------|
| `app/git_data/extract_git_data.py` | Repository cloning, commit extraction | Extraction |
| `app/git_data/extract_pr_data.py` | GitHub API PR fetching | Extraction |
| `app/git_data/etl_pipeline.py` | Orchestration + ETL transform | Transformation |
| `app/git_data/models.py` | Pydantic data models | Schema |
| `app/summarize/commit_summarizer.py:~405Lo lines` | Core summarization logic | LLM Processing |
| `app/summarize/summarize_commits.py` | CLI entry point | Orchestration |
| `app/summarize/summarizer_config.py` | Environment + prompt configuration | Configuration |
| `app/vectordb/load_summaries.py` | ChromaDB loading logic | Vector Store |
| `app/notebooks/run_notebook.py` | Jupyter execution utility | Utility |
| `app/utils/logging.py` | Logger singleton setup | Support |

---

**End of Architecture Summary**
