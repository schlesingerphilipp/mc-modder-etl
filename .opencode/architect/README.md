# Architecture Documentation for Minecraft Commit Summarization System

This directory contains architecture documentation to help development assistants understand the ETL pipeline that extracts Git commits and PR data from Minecraft repositories, generates LLM-powered semantic summaries, and outputs enriched CSVs.

## Files in This Directory

| File | Purpose |
|------|---------|
| `architecture-summary.md` | System-level overview with ASCII diagrams, module interaction map, data flow descriptions, and external API integration documentation |
| `README.md` | Documentation navigation and guide |
| `prompts.md` | Templates for AI assistants reviewing this codebase |

## Usage Guide

### For Development Assistants

When analyzing or modifying the codebase:

1. **Start with `architecture-summary.md`** to understand system boundaries and data flow
2. **Consult module-specific docs** in `app/docs/` for detailed implementation info:
   - `app/docs/git_data_architecture.md` — Extract & Transform logic
   - `app/docs/summarize_architecture.md` — LLM summarization with checkpoints
   - `app/docs/vectordb_architecture.md` — ChromaDB integration
   - `app/docs/utils_architecture.md` — Logging utilities
   - `app/docs/notebooks_architecture.md` — Notebook execution support

### Key Concepts to Understand

- **Partitioned Parquet**: Output uses PyArrow partitioning by `{Repo ID}/{commit hash}`
- **Checkpoint Resume**: Summarizer saves progress per-file, enabling graceful restarts
- **Diff Truncation**: Per-file diffs limited to 8000 chars, with marker for LLM awareness
- **Prompt Templates**: File-based prompts (`.md`) loaded at runtime via Jinja-style formatting

### External Services Integration

The system integrates with:

1. **GitHub REST API** — Fetch PR metadata from public repositories
2. **LLM Providers** — Supports:
   - Google Gemini (via `GOOGLE_API_KEY`)
   - LM Studio (localhost inference: `http://host.docker.internal:1234/v1`)
   - Any OpenAI-compatible API
3. **ChromaDB** — Vector database for storing summaries with embeddings

### Environment Variables Required

Minimum set to run all commands:

```bash
# Required for summarization
export LMSTUDIO_BASE_URL="http://host.docker.internal:1234/v1"

# Optional but recommended
export CHECKPOINT_DIR="./checkpoints"
export MAX_RETRIES="3"
export TIMEOUT_SECONDS="60"

# For ChromaDB integration
export CHROMA_HOST="chromadb"
export CHROMA_PORT="8000"
export CHROMA_COLLECTION="commit_summaries"
```

See `architecture-summary.md` for full reference.

### CLI Commands Quick Reference

| Command | Description |
|---------|-------------|
| `poetry run etl-pipeline` | Extract commits + PRs → Parquet |
| `poetry run summarize-commits /var/db/git_data/ /var/db/summaries` | Generate summaries |
| `poetry run load-summaries /var/db/summaries --mode full` | Load into ChromaDB |
| `poetry run run-notebook app/notebooks/summary_analysis.py` | Run analysis notebook |

### Testing Without API Keys

All tests are fully mocked. No external dependencies required:

```bash
make test    # Run all pytest tests with verbose output
make lint    # Lint with pylint on app/ and tests/
make format-check    # Check Black formatting
```

### Architecture Documentation Structure

Each architecture document follows this template from `prompts.md`:

1. **Module Overview** — Purpose and responsibilities
2. **Data Structures (Pydantic models)** — If applicable
3. **Entry Points** — CLI interfaces or programmatic entry points
4. **Dependencies** — Imports and external services
5. **Key Algorithms** — Core logic and transformations
6. **Diff Truncation Limits** — Applied thresholds and behaviors
7. **Checkpoint/Resume Patterns** — If applicable

## Contributing to Documentation

### Adding Module Architecture Docs

When adding a new module or major changes, create/update:
- File in `app/docs/` following existing patterns
- Update `architecture-summary.md` if system-wide behavior changed
- Document any new design decisions in relevant docs

### Updating Prompt Templates

If modifying prompts, update both:
1. The prompt template file (e.g., `PROMPT.md`)
2. Architecture documentation referencing it

## Related Documentation Referenced By These Files

- `/home/vscode/workspace/app/git_data/etl-plan.md` — ETL pipeline design decisions
- `/home/vscode/workspace/app/summarize/SUMMARIZER_IMPLEMENTATION.md` — Summarizer architecture and checkpoint system
- `/home/vscode/workspace/.opencode/plans/etl-pipeline-output-change.md` — Recent ETL output path changes

## Notes for AI Assistants

When making changes to this codebase:

1. **Always check existing documentation** before implementing features
2. **Maintain the Pydantic model pattern** using Field descriptions for schema docs
3. **Use space-separated CSV column names** for downstream compatibility
4. **Add appropriate error handling** with retry logic and logging
5. **Follow checkpoint patterns** for long-running processes
6. **Document breaking changes** in relevant architecture files
