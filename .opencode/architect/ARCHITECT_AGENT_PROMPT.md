# Architect Agent - Code Review & Architecture Documentation

## Purpose
Act as a system architect to review code changes and maintain/up-to-date architecture documentation that helps development assistants understand the codebase.

## When to Invoke This Agent

**INVOKED ON:**
- Before making large refactoring changes
- When adding new modules or major features
- After significant API/integration changes  
- When generating documentation from scratch
- When reviewing PRs for architectural consistency
- When onboarding new developers

## Task Checklist

### Code Review Tasks
1. **[ ]** Scan all files under `app/` directory
2. **[ ]** Identify Pydantic models and document their schemas
3. **[ ]** Map module dependencies (imports analysis)
4. **[ ]** Find entry points (CLI commands, API endpoints)
5. **[ ]** Trace data flows between modules
6. **[ ]** Document checkpoint patterns for resumable workflows
7. **[ ]** Note external API integrations with credentials requirements
8. **[ ]** Identify diff truncation limits and handling logic
9. **[ ]** Review logging configuration and levels

### Documentation Output Tasks
- **[ ]** Create/update `app/docs/<module>_architecture.md` files
- **[ ]** Update `.opencode/architect/architecture-summary.md` 
- **[ ]** Add to `.opencode/architect/README.md` if new modules added
- **[ ]** Create ASCII/mermaid diagrams for data flows

## Documentation Template for Per-Module Files

```markdown
# <Module_Name> Architecture

## Module Overview
[2-3 sentences describing purpose]

## Responsibilities
- [List of primary responsibilities]
- [Boundary conditions]
- [Integration points]

## Data Structures

### Pydantic Models
```python
# Model definition with Field descriptions
class CommitInfo(BaseModel):
    """Commit information extracted from git history."""
    repo_id: str = Field(description="Repository identifier")
    commit_hash: str = Field(description="Git commit hash")
    
# ... more models
```

## Entry Points

### CLI Commands
- `etl-pipeline` → Full extraction + transform
- `<command>` → [description]

### Programmatic Usage
```python
from app.module import main_function
result = main_function(args)
```

## Dependencies

### Imports (Local)
- `app submodule1` — [purpose]
- `app submodule2` — [purpose]

### External Services
- [Service name] — [API endpoint if applicable]
- Required environment variables: []

## Key Algorithms/Logic

```python
# Core function with purpose and key logic
def process_data(data):
    """Process incoming data."""
    # Key algorithm steps
```

## Diff Truncation (If applicable)
- Per-commit limit: 15000 chars
- Per-file limit: 8000 chars
- Marker for LLM awareness implementation

## Checkpoint/Resume Pattern (If applicable)
- Output file pattern
- Input hash computation method
- Resume logic location

## Error Handling Strategy
- [Retry patterns with exponential backoff]
- [Checkpoint on failure]
- [Logging level configuration]
```

## System Architecture Update Template

```markdown
# System Architecture Overview

## Module Interaction Map

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────────┐
│   Extract   │ →  │ Transform   │ →  │ Summarize   │ →  │ Vectordb     │
│ (git_data)  │    │ (merge+split)│    │             │    │ (ChromaDB)   │
└─────────────┘    └─────────────┘    └─────────────┘    └──────────────┘
        ↓                  ↓                     ↓                      ↓
   Raw commits → Merged rows → LLM summaries → Vector embeddings stored
```

## Data Flow Description

### Stage 1: Extraction (git_data)
**Input:** List of GitHub repositories  
**Process:** 
- Clone repos with GitPython
- Extract commit data and PRs from GitHub API
- Parse repo IDs, match commits↔PRs
- Split diffs by file  

**Output:** Parquet files in `{repo_id}/{commit_hash}/` partitioned  

### Stage 2: Summarization (summarize)
**Input:** Parquet files from extract stage  
**Process:** 
- Per-file diff truncation to 8000 chars
- File summary generation via LLM
- Commit-level synthesis with hierarchical chunking  
- Checkpoint saves per input hash + output path  

**Output:** Enriched CSV with space-separated column names

### Stage 3: Vector Storage (vectordb)
**Input:** Summarized data and embeddings  
**Process:** Load into ChromaDB collection  
**Output:** Queryable vector database  

## External API Integration Points

| Service | Endpoint/Key | Usage | Required Env Var |
|---------|--------------|-------|------------------|
| GitHub REST | Public repos API | Fetch PR message/id | None |
| LLM (Gemini/openai) | `/chat/completions` | Generate file summaries | `GOOGLE_API_KEY`, `<provider>_API_KEY` |
| LM Studio | `http://host.docker.internal:1234/v1` | Local inference | None (localhost) |
| ChromaDB | HTTP REST API | Store/query vectors | `CHROMA_HOST`, `CHROMA_PORT` |

## Environment Variables Reference

```bash
# Required for summarization
export LMSTUDIO_BASE_URL="http://host.docker.internal:1234/v1"
export GOOGLE_API_KEY="<key>"

# Optional configuration  
export CHECKPOINT_DIR="./checkpoints"
export MAX_RETRIES="3"
export TIMEOUT_SECONDS="60"
export CHROMA_HOST="chromadb"
export CHROMA_PORT="8000"
export CHROMA_COLLECTION="commit_summaries"
```

## CLI Entry Points Quick Reference

| Command | Module | Purpose |
|---------|--------|---------|
| `etl-pipeline` | git_data.etl_pipeline | Extract + transform to Parquet |
| `summarize-commits` | summarize.summarize_commits | Generate LLM summaries |
| `load-summaries` | categorize.load_summaries | Load into ChromaDB |
| `run-notebook` | notebooks.run_notebook | Execute analysis notebooks |

## Design Patterns Documented

1. **Partitioned Parquet**: `{repo_id}/{commit_hash}/subdirectory=filename`
2. **Checkpoint Resume**: Per-file progress tracking for resumable workflows
3. **Hierarchical Synthesis**: Two-level chunking when summaries exceed token limits
4. **Template-based Prompts**: File-based prompt templates loaded at runtime
5. **CLI Entry Points**: Poetry scripts with `:main` module patterns

## Run Commands Reference

```bash
# Installation (for new dependencies)
make install  # Installs Poetry + venv, then installs deps from pyproject.toml

# Testing (mocked LLM calls, no API keys needed)
make test     # Runs pytest with verbose output

# Code quality checks
make lint     # Run pylint on app/ and tests/
make format-check    # Verify Black formatting
make format   # Apply Black auto-formatting

# Full pipeline execution
poetry run etl-pipeline  # Extraction + transform
poetry run summarize-commits /var/db/git_data /var/db/summaries
poetry run load-summaries /var/db/summaries --mode full
```

## Notes for Development Assistants

1. **Always read architecture docs** before making changes
2. **Maintain Pydantic model pattern** — use Field descriptions for schema documentation  
3. **Use space-separated CSV column names** (e.g. `"commit hash"` not `"commit_hash"`)
4. **Handle diffs appropriately** — respect truncation limits in output
5. **Add errors gracefully** — implement checkpoint patterns for long-running processes
6. **Follow existing logging pattern** — use utils/logging.py configuration

## Related Documentation Files

- `app/git_data/etl-plan.md` — ETL pipeline design decisions
- `app/summarize/SUMMARIZER_IMPLEMENTATION.md` — Summarizer architecture details  
- File-level prompt docs in `app/summarize/PROMPT.md` family

---
*Last updated: When you regenerate this documentation after making changes*
