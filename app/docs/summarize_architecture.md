# Summarize Module Architecture

## Overview

The `summarize` module is responsible for generating semantic summaries of git commits using LLM APIs. It processes the raw commit data from the ETL output, generates per-file summaries, synthesizes them into commit-level summaries, and writes results to partitioned Parquet files with support for checkpoint-based resume functionality.

### Module Location
```
app/summarize/
├── commit_summarizer.py  # Core summarization logic
├── summarize_commits.py   # CLI entry point
├── summarizer_config.py   # Configuration from environment + prompts
├── PROMPT.md              # Commit synthesis prompt template
├── FILE_SUMMARY_PROMPT.md # File-level summary prompt
└── COMMIT_SYNTHESIS_PROMPT.md  # Commit synthesis prompt
```

### Module Responsibilities
- Load partitioned Parquet data containing commit diffs
- Group commits and split their diffs into file components
- Generate LLM summaries for each file's diff
- Synthesize file summaries into cohesive commit-level summaries
- Write results incrementally to partitioned Parquet (supports resume)
- Handle checkpointing per commit/file pair

---

## Data Structures (Pydantic Models)

Located in `app/summarize/models.py`:

### `CommitSummaryResult` Model
```python
class CommitSummaryResult(BaseModel):
    """The summary of a commit diff"""
    semantic_summary: str
```

**Purpose:** Represents an LLM response containing the final commit summary.

### `FileSummaryResult` Model
```python
class FileSummaryResult(BaseModel):
    """The summary of a single file diff"""
    file_summary: str
```

**Purpose:** Represents an LLM response for a single file's changes.

Note: These are used for type hinting but the actual response parsing returns raw strings from JSON extraction.

---

## Entry Points and CLI Interfaces

### Poetry Script: `summarize-commits`
Located in `app/summarize/summarize_commits.py`, registered as the `summarize-commits` command.

```python
def main() -> int:
    """Main entry point for commit summarization."""
    # Arguments:
    #   input_file    - Path to input ETL Parquet (default: /var/db/git_data/)
    #   output_dir    - Path to output summaries (default: /var/db/summaries)
    #   --verbose     - Enable detailed logging
    
    # Operations:
    #   1. Load and validate input Parquet
    #   2. Initialize LLM client (Config)
    #   3. Process commits with incremental writes
    #   4. Resume from checkpoints if needed
    
return 0  # success, 1 on failure
```

**Usage:**
```bash
poetry run summarize-commits /var/db/git_data /var/db/summaries
# or with options:
poetry run summarize-commits input.parquet output_dir --verbose
```

**Output:** Partitioned Parquet at `output_dir/Repo ID={X}/commit hash={Y}/...parquet`

### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `<input_file>` | `/var/db/git_data` | Path to input partitioned Parquet |
| `<output_dir>` | `/var/db/summaries` | Partitioned output directory |
| `-v,--verbose` | false | Enable detailed logging |

---

## Dependencies

### External Services
1. **LangChain + ChatOpenAI** (`langchain_openai.ChatOpenAI`)
   - LLM client wrapper for Google-compatible APIs
   - Configured with environment variables (LM Studio by default)

2. **Pandas** (`pandas`)
   - Dataframe operations for grouping, iterating commits
   - Parquet I/O via pyarrow

### Environment Variables (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `LMSTUDIO_MODEL` | `gpt-oss-20b` | LLM model name |
| `LMSTUDIO_BASE_URL` | `http://host.docker.internal:1234/v1` | LLM API endpoint |
| `LMSTUDIO_API_KEY` | `not-needed` | API key (unused for LM Studio) |
| `MAX_RETRIES` | `3` | Max retries per LLM call |
| `TIMEOUT_SECONDS` | `60` | Request timeout |
| `MAX_DIFF_LENGTH` | `15000` | Max total diff length |
| `MAX_FILE_DIFF_LENGTH` | `8000` | Max per-file diff length |
| `MAX_SYNTHESIS_LENGTH` | `8000` | Trigger chunking threshold |
| `CHECKPOINT_DIR` | `CWD/checkpoints` | Checkpoint directory path |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |

### Prompt Template Files
Read from same directory as config module:
- `PROMPT.md` → Commit synthesis prompt template
- `FILE_SUMMARY_PROMPT.md` → File summary prompt template
- `COMMIT_SYNTHESIS_PROMPT.md` → Commit synthesis prompt template

---

## Key Algorithms and Logic

### Core Architecture Pattern

The `CommitSummarizer` class uses a "file-first" approach:
1. **Group** ETL rows by commit hash → `Dict[hash, DataFrame]`
2. **Per-file checkpointing**: Save progress after each file summarized
3. **Hierarchical synthesis**: When summaries exceed limit, chunk → summarize chunks → synthesize final

### Main Processing Flow (`process_commits`)

```python
def process_commits(df: pd.DataFrame, output_dir: Path) -> Dict[str, int]:
    """Process all commits and write summaries incrementally."""
    
    for commit_hash, group in group_rows_by_commit(df).items():
        repo_id = str(group.iloc[0]["Repo ID"])
        
        # Check if already processed (parquet partition exists)
        if _commit_exists(output_dir, repo_id, commit_hash):
            skipped += 1
            continue
        
        try:
            # File-level processing with checkpointing
            file_summaries = summarize_commit_files(group, checkpoint_path=cp_path)
            
            # Generate commit-level summary
            summary = synthesize_commit_summary(commit_message, file_summaries)
            
            # Write to partitioned Parquet
            _write_commit_summary(output_dir, group, summary)
            
            processed += 1
            # Clean up temporary checkpoint
            _delete_file_checkpoint(cp_path)
            
        except Exception as e:
            failed += 1
            
    return {"processed": processed, "skipped": skipped, "failed": failed}
```

---

### File Summary Generation (`summarize_file_diff`)

```python
def summarize_file_diff(self, file_path: str, diff: str) -> str:
    """Generate summary for a single file's diff."""
    
    # Truncate if needed (config.max_file_diff_length = 8000 by default)
    truncated = False
    orig_length = len(diff)
    if len(diff) > self.config.max_file_diff_length:
        diff = diff[:self.config.max_file_diff_length]
        truncated = True
        LOGGER.warning(f"File diff truncated from {orig_length} to "
                       f"{self.config.max_file_diff_length} chars")
    
    # Format prompt
    if truncated:
        diff_for_prompt = diff + "\n\n[... DIFF TRUNCATED ...]"
        prompt = config.file_summary_prompt_template.format(
            file_path=file_path, diff=diff_for_prompt
        )
    else:
        prompt = config.file_summary_prompt_template.format(
            file_path=file_path, diff=diff
        )
    
    # Invoke LLM with retry logic
    last_error = None
    for attempt in range(self.config.max_retries):
        try:
            response = self.file_client.invoke(prompt)
            content = response.content.strip()
            
            if not content:
                raise ValueError("LLM returned empty content")
            
            # Parse JSON response
            parsed = json.loads(content)
            return parsed["file_summary"]
            
        except Exception as e:
            last_error = e
            if attempt < self.config.max_retries - 1:
                LOGGER.warning(f"File summary LLM call failed: {e}")
    
    # Retry exhausted
    raise Exception(f"File summary LLM call failed after retries") from last_error
```

**Key Points:**
- Excessive diffs are truncated with marker `[... DIFF TRUNCATED ...]`
- Response must be JSON-parsable with `file_summary` key
- Empty responses raise ValueError
- Retries up to `MAX_RETRIES` times before failure

---

### Per-File Checkpointing System

```python
def _file_checkpoint_path(self, output_dir: Path, repo_id: str, commit_hash: str) -> Path:
    """Get checkpoint path for file summaries of a specific commit."""
    encoded_repo = quote(repo_id, safe="")
    checkpoint_dir = output_dir / f"Repo ID={encoded_repo}" / f"commit hash={commit_hash}"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    return checkpoint_dir / "_file_summaries.json"

def _load_file_checkpoint(self, checkpoint_path: Path) -> List[Dict[str, str]]:
    """Load previously checkpointed file summaries."""
    if not checkpoint_path.exists():
        return []
    try:
        with open(checkpoint_path, "r") as f:
            return json.load(f)
    except Exception:
        LOGGER.warning(f"Failed to load file checkpoint")
        return []

def _save_file_checkpoint(self, checkpoint_path: Path, file_summaries: List[Dict[str, str]]) -> None:
    """Save file summaries checkpoint after summarizing files."""
    with open(checkpoint_path, "w") as f:
        json.dump(file_summaries, f, indent=2)

def _delete_file_checkpoint(self, checkpoint_path: Path) -> None:
    """Remove checkpoint after commit is fully written."""
    try:
        checkpoint_path.unlink(missing_ok=True)
    except Exception:
        LOGGER.warning(f"Failed to delete checkpoint")
```

**Checkpoint Structure:**
```json
[
  {"file": "src/main.py", "summary": "Added user authentication flow"},
  {"file": "README.md", "summary": "Updated documentation"}
]
```

**Resume Pattern:**
- Each run checks if partition exists (`_commit_exists`)
- If not, checkpoint is used to resume from previous partial work
- Checkpoint deleted only after successful commit write

---

### Commit Summary Synthesis (`synthesize_commit_summary`)

```python
def synthesize_commit_summary(self, commit_message: str, file_summaries: List[Dict[str, str]]) -> str:
    """Synthesize file summaries into a commit-level summary."""
    
    if not file_summaries:
        return "No file changes to summarize."
    
    formatted_lines = [
        f"- {fs['file']}: {fs['summary']}" for fs in file_summaries
    ]
    return self.synthesize_summary_chunking(commit_message, formatted_lines)
```

---

### Hierarchical Synthesis with Chunking (`synthesize_summary_chunking`)

When combined summaries exceed `MAX_SYNTHESIS_LENGTH` (8000 by default):

```python
def synthesize_summary_chunking(self, commit_message: str, formatted_lines: list[str]) -> str:
    """Handle long file summaries via hierarchical chunking and synthesis."""
    
    max_len = self.config.max_synthesis_length
    summary = "\n".join(formatted_lines)
    
    if len(summary) <= max_len:
        # Single LLM call is sufficient
        return self._invoke_synthesis(commit_message, summary)
    
    # Split into chunks that fit within max_len
    LOGGER.info(f"File summaries too long ({len(summary)} chars), chunking")
    
    chunks = []
    current_chunk = []
    current_len = 0
    
    for line in formatted_lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_len:
            # Start new chunk
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(line)
        current_len += line_len
    
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    
    LOGGER.info(f"Split into {len(chunks)} chunks")
    
    # Summarize each chunk
    chunk_summaries = []
    for i, chunk in enumerate(chunks, 1):
        summary = self._invoke_synthesis(commit_message, chunk)
        chunk_summaries.append(summary)
    
    # Final synthesis of chunk summaries
    return self.synthesize_summary_chunking(commit_message, chunk_summaries)
```

**Why Hierarchical Chunking?**
- LLM context windows have limits
- Complex commits with many files may exceed 8000 chars of formatted summaries
- Chunk → summarize each → synthesize final produces high-quality holistic summary

---

### Prompt Templates Format

Prompts are read from `.md` files and use Python format strings:

**File Summary Prompt (`FILE_SUMMARY_PROMPT.md`):**
```markdown
# FILE_SUMMARY_PROMPT
Summarize the changes in this file in 1-2 sentences.

File: {file_path}

Diff:
{diff}

Respond with ONLY a JSON object in this exact format (no other text):
{{"file_summary": "your summary here"}}
```

**Format Usage:**
```python
prompt = self.config.file_summary_prompt_template.format(
    file_path=file_path,
    diff=diff
)
```

---

### LLM Invocation with Retry Logic

```python
def _invoke_synthesis(self, commit_message: str, formatted_summaries: str) -> str:
    """Invoke synthesis LLM and parse JSON response."""
    
    prompt = self.config.commit_synthesis_prompt_template.format(
        commit_message=commit_message,
        file_summaries=formatted_summaries
    )
    
    last_error = None
    for attempt in range(self.config.max_retries):
        try:
            response = self.commit_client.invoke(prompt)
            content = response.content.strip()
            
            if not content:
                raise ValueError("LLM returned empty content")
            
            parsed = json.loads(content)
            return parsed["semantic_summary"]
            
        except Exception as e:
            last_error = e
            if attempt < self.config.max_retries - 1:
                LOGGER.warning(f"Synthesis LLM call failed (attempt {attempt + 1}): {e}")
    
    # All retries exhausted
    raise Exception(f"Synthesis LLM call failed after {self.config.max_retries} attempts") from last_error
```

**Error Handling:**
- Empty responses → ValueError
- Non-JSON responses → ParseError wraps in outer exception
- Network errors on retry N+1st attempt → Full exception raised

---

### Diff Truncation Limits

The summarize module implements two truncation layers:

| Layer | Limit | Config Key | Purpose |
|-------|-------|------------|---------|
| Per-commit diff | 15000 chars | `MAX_DIFF_LENGTH` | Not currently enforced in this code |
| Per-file diff | 8000 chars | `MAX_FILE_DIFF_LENGTH` | Enforced before LLM call |
| Synthesis input | 8000 chars | `MAX_SYNTHESIS_LENGTH` | Triggers chunking |

**Truncation Logic:**
```python
if len(diff) > self.config.max_file_diff_length:
    diff = diff[:self.config.max_file_diff_length]
    truncated = True
    LOGGER.warning(f"File diff truncated to {max_file_diff_length} chars")
    
    # Add marker for LLM to understand truncation occurred
    if truncated:
        formatted_diff = diff + "\n\n[... DIFF TRUNCATED ...]"
```

---

### Checkpoint/Resume Patterns

**Per-Commit Resume:**
```python
def _commit_exists(self, output_dir: Path, repo_id: str, commit_hash: str) -> bool:
    """Check if summary already exists in output partitioned Parquet."""
    encoded_repo = quote(repo_id, safe="")
    partition_path = output_dir / f"Repo ID={encoded_repo}" / f"commit hash={commit_hash}"
    return partition_path.exists() and any(partition_path.glob("*.parquet"))
```

**Per-File Resume:**
- Checkpoint saved after each file is summed (inside `summarize_commit_files`)
- Resumed on next run for commits without partition yet
- Deleted after commit successfully written to Parquet

**Why Two-Level Resume?**
- Fast failure: Can skip entire commits if already processed
- Granular recovery: If file-level checkpoint exists, resume that specific commit
- Clean termination: Checkpoint deleted prevents duplicate work

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                            SUMMARIZE Module                          │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    INPUT: Partitioned Parquet                │    │
│  │              {Repo ID}/{commit hash}/summary.parquet         │    │
│  │                                                              │    │
│  │   Columns: Repo ID, commit hash, commit message,            │    │
│  │            PR message, PR ID, diff                           │    │
│  └────────────┬─────────────────────────────────────────────────┘    │
│               │                                                       │
│               ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │              GROUP BY COMMIT HASH                            │    │
│  │                                                              │    │
│  │   {commit_hash: DataFrame(grouped_rows)}                    │    │
│  │                                                              │    │
│  └───────────▲──────────────────────────────────────────────────┘    │
│              │                                                     │
│              ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │      PER-COMMIT PROCESSING LOOP                              │    │
│  │                                                              │    │
│  │   For each commit hash:                                      │    │
│  │     ├─ Check if parquet partition exists                      │    │
│  │     ├─ If yes → skip (skipped counter)                        │    │
│  │     └─ If no → process:                                       │    │
│  │          │                                                   │    │
│  │          ▼                                                    │    │
│  │   ┌─────────────────────────────────────────────┐            │    │
│  │   │    File-Level Summarization & Checkpoint    │            │    │
│  │   │                                             │            │    │
│  │   │   For each file diff in commit:             │            │    │
│  │   │     ├─ Extract file path from diff header    │            │    │
│  │   │     ├─ Truncate if > MAX_FILE_DIFF_LENGTH    │            │    │
│  │   │     ├─ Format FILE_SUMMARY_PROMPT           │            │    │
│  │   │     ├─ Invoke LLM (with retries + timeout)   │            │    │
│  │   │     ├─ Parse JSON response                   │            │    │
│  │   │     ├─ Save to file_summaries list          │            │    │
│  │   │     └─ CHECKPOINT → _file_summaries.json     │            │    │
│  │   └─────────────────────────────────────────────┘            │    │
│  │                                                              │    │
│  │   After all files summarized:                               │    │
│  │                                                              │    │
│  │   ┌─────────────────────────────────────────────┐            │    │
│  │   │    Commit-Level Synthesis                   │            │    │
│  │   │                                             │            │    │
│  │   │     1. Format file summaries for synthesis  │            │    │
│  │   │     2. If total > MAX_SYNTHESIS_LENGTH:     │            │    │
│  │   │         └→ Chunk → Summarize chunks →      │            │    │
│  │   │              Synthesize final                   │         │    │
│  │   │     3. Invoke COMMIT_SYNTHESIS_PROMPT       │            │    │
│  │   │     4. Parse JSON response                  │            │    │
│  │   └─────────────────────────────────────────────┘            │    │
│  │                                                              │    │
│  │          ▼                                                   │    │
│  │   ┌─────────────────────────────────────────────┐            │    │
│  │   │    WRITE TO PARTITIONED PARQUET            │            │    │
│  │   │                                             │            │    │
│  │   │     Output: {Repo ID}/{commit hash}/       │            │    │
│  │   │              semantic_summary.parquet        │            │    │
│  │   │                                             │            │    │
│  │   └─────────────────────────────────────────────┘            │    │
│  │                                                              │    │
│  │          ▼                                                   │    │
│  │   ┌─────────────────────────────────────────────┐            │    │
│  │   │    DELETE FILE CHECKPOINT                   │            │    │
│  │   │         (after successful write)            │            │    │
│  │   └─────────────────────────────────────────────┘            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module Interaction Map

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                                   SUMMARIZE                                     │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                   app/summarize/commit_summarizer.py                     │   │
│  │                                                                          │   │
│  │  Class: CommitSummarizer                                                 │   │
│  │                                                                          │   │
│  │  Dependencies:                                                           │   │
│  │    • SummarizerConfig (from environment)                                 │   │
│  │    • LangChain ChatOpenAI                                               │   │
│  │    • Prompts loaded from .md files                                       │   │
│  │                                                                          │   │
│  │  Key Methods:                                                            │   │
│  │    - summarize_file_diff(): Summarize single file                        │   │
│  │    - synthesize_commit_summary(): Synthesize commit-level summary         │   │
│  │    - process_commits(): Main orchestration loop                          │   │
│  │    - _invoke_synthesis(): LLM call with retry logic                      │   │
│  │                                                                          │   │
│  └───────────────────────────────────────▲──────────────────────────────────┘    │
│                                          │                                       │
│                              checkpoint/resume pattern                           │
│                                          │                                       │
│  ┌───────────────────────────────────────▼──────────────────────────────────┐   │
│  │              app/summarize/summarize_commits.py (CLI)                     │   │
│  │                                                                          │   │
│  │  Entry Point: summarize-commits                                           │   │
│  │    • argparse for CLI arguments                                           │   │
│  │    • validate_input(): Load and validate Parquet                          │   │
│  │    • main(): Orchestration                                               │   │
│  │      - Initialize CommitSummarizer                                        │   │
│  │      - Call process_commits()                                              │   │
│  │      - Exit with status code (0 success, 1 error)                         │   │
│  └───────────────────────────────────────▲──────────────────────────────────┘    │
│                                          │                                       │
│                          Input: Partitioned Parquet                               │
│                          DB_PATH/git_data                                        │
│                          (from etl-pipeline output)                               │
│                                          │                                       │
│  ┌───────────────────────────────────────▼──────────────────────────────────┐   │
│  │              app/summarize/summarizer_config.py                           │   │
│  │                                                                          │   │
│  │  Class: SummarizerConfig                                                  │   │
│  │    • Loads LMSTUDIO_* environment variables                               │   │
│  │    • Reads prompt templates from .md files                                │   │
│  │    • Provides MAX_* configuration values                                  │   │
│  └───────────────────────────────────────▲──────────────────────────────────┘    │
│                                          │                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐     │
│  │                   app/utils/logging.py                                   │     │
│  │                                                                          │     │
│  │  Module: logging                                                         │     │
│  │    • LOGGER configured with LOG_LEVEL env var                            │     │
│  │    • Logs: commit processing, truncation, retries, errors                │     │
│  └─────────────────────────────────────────────────────────────────────────┘     │
│                                                                                │
│              External Dependencies                                              │
│      • Google Gemini / LMStudio API (via LangChain)                             │
│        - Endpoint: http://host.docker.internal:1234/v1                        │
│        - Model: gpt-oss-20b or custom                                          │
│                                                                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## CLI Entry Point Registration (pyproject.toml)

Registered as Poetry command in project root:
```toml
[tool.poetry.scripts]
summarize-commits = "app.summarize.summarize_commits:main"
```

---

## Testing Pattern

Located in `tests/summarize/`:
- Uses mocked LLM responses for all tests
- Tests checkpoint loading/saving logic
- Verifies truncation behavior
- Validates error handling patterns

No LLM API keys required for tests.

