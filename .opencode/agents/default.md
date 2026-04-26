# Agents Configuration

## Project Overview

ETL pipeline that extracts git diffs and commit/PR messages from Minecraft repositories, generates LLM-powered semantic summaries, and outputs enriched CSVs.

Project structure:
- `app/git_data/` → Extract: clone repos, extract commits & PRs
- `app/summarize/` → Generate per-file + per-commit LLM summaries
- `app/notebooks/` → Analysis notebooks
- `app/utils/` → Shared utilities (logging)

## Build and Test

Use `make` targets — do not call Poetry or pytest directly:

- `make install` — install all dependencies (Poetry, in-project `.venv`)
- `make lock` — update `poetry.lock` after changing `pyproject.toml`
- `make test` — run pytest with verbose output
- `make lint` — pylint on `app/` and `tests/`
- `make format` — apply Black formatting
- `make format-check` — verify formatting without changes

When running Python directly, activate `.venv` first. Add new dependencies to `pyproject.toml`, not via `pip install`.

## CLI Entry Points

Three registered Poetry scripts:

| Command | Module | Purpose |
|---------|--------|---------|
| `etl-pipeline` | `app.git_data.etl_pipeline` | Full extraction + transform pipeline |
| `summarize-commits` | `app.summarize.summarize_commits` | LLM semantic summary generation |
| `run-notebook` | `app.notebooks.run_notebook` | Programmatic notebook execution |
| `load-summaries` | `app.vectordb.load_summaries` | Load summaries into vector database |

Run via `poetry run <command>` or activate the venv first.

## Architecture Documentation System

The `/home/vscode/workspace/.opencode/architect/` directory contains architecture documentation and tools for development assistants:

### Files Available

| File | Purpose |
|------|---------|
| `.opencode/architect/architecture-summary.md` | System-level overview with module interaction map, data flow descriptions, external API integration documentation |
| `app/docs/git_data_architecture.md` | Extract & Transform module architecture |
| `app/docs/summarize_architecture.md` | LLM summarization with checkpoint resume patterns |
| `app/docs/vectordb_architecture.md` | ChromaDB vector database integration |
| `app/docs/utils_architecture.md` | Logging utilities |
| `app/docs/notebooks_architecture.md` | Jupyter notebook execution support |

### Using the Code Architect Agent

The **Code Architect** skill can be invoked to:

1. Review the entire codebase under `app/`
2. Create or update architecture documentation
3. Document data flows between modules
4. Help AI coding assistants understand the system

**Command:** `code-architect`

**When to use:**
- Before making large refactoring changes
- When adding new modules or major features  
- After significant API/integration changes
- For onboarding new developers or AI agents
- When reviewing PRs for architectural consistency

See `.opencode/architect/SUMMARY.txt` for detailed usage instructions.

## Architecture

```
app/git_data/       → Extract: clone repos, extract commits (GitPython) & PRs (GitHub API)
                     → Transform: parse repo IDs, match commits↔PRs, split diffs by file
app/summarize/      → Summarize: per-file + per-commit LLM summaries with checkpoint resume
app/notebooks/      → Analysis notebooks and runner
app/utils/          → Shared logging (LOG_LEVEL env var)
```

Data flow: Extract → Transform → Summarize (resumable via checkpoints) → CSV output

## Conventions

- **Python >=3.11** with Poetry for dependency management
- **Pydantic models** in `app/git_data/models.py` for all data structures (Commit, PR, ETLRow, CommitSummary)
- **LangChain** for LLM integration — supports OpenAI-compatible APIs (Gemini, LM Studio)
- **Checkpoint system** in `app/summarize/commit_summarizer.py` — saves progress per input hash + output path
- CSV columns use space-separated names (e.g. `"commit hash"`, not `"commit_hash"`)
- Diff truncation limits: `MAX_DIFF_LENGTH=15000` per commit, `MAX_FILE_DIFF_LENGTH=8000` per file

## Environment

Requires a `.env` file with:
- `GOOGLE_API_KEY` — for Gemini API access
- `GEMINI_MODEL` — model name (default: `gemini-1.5-pro`)

Optional: `CHECKPOINT_DIR`, `MAX_RETRIES`, `TIMEOUT_SECONDS`, `LOG_LEVEL`

LM Studio local inference available via `http://host.docker.internal:1234/v1` (Docker/devcontainer only).

## Testing

- Tests use `pytest` with mocked LLM calls — no API keys needed for tests
- Test fixtures for diffs in `tests/git_data/resources/`
- One test file per module (e.g. `tests/test_commit_summarizer.py` ↔ `app/summarize/commit_summarizer.py`)

## Key Documentation

When creating new plans, check these files first:

### Essential Files to Review Before Creating a Plan

1. **Check existing documentation:**
   - `/home/vscode/workspace/app/git_data/etl-plan.md` — ETL pipeline design decisions
   - `/home/vscode/workspace/app/summarize/SUMMARIZER_IMPLEMENTATION.md` — Summarizer architecture and checkpoint system
   - `/home/vscode/workspace/.opencode/plans/etl-pipeline-output-change.md` — Recent changes to ETL output path

2. **Existing Python files** in relevant directories

3. **Recent commits** — review git history for context on ongoing changes

### Plan Format Requirements

All plans should follow this structure:

#### # Current State
- Identify the problem or requested change with specific file paths and line numbers where applicable
- Note any hardcoded values, missing environment variable support, or incorrect implementations

#### ## Required Changes
For each file that needs modification:

##### File: filename (lines 1-X)
Add/replace code block showing exact changes needed
Include:
- Import statements
- New functions/classes/models
- Function signatures and docstrings
- Full implementation with proper error handling

When modifying existing code, show the complete new replacement function/method

#### ## Run Command
The command to test after changes are applied:
```bash
make install  # if dependencies need updating
make test     # to verify tests pass
python -m module.name  # or CLI command from poetry scripts
```

#### ## Expected Output
- Where output files will be created
- Any environment variables needed
- Default paths and configurable parameters

### Common Patterns for Plan Generation

When modifying data processing functions:

1. **Define configuration constants** with environment variable fallbacks at module level
2. **Use Pydantic models** for all structured data (Commit, PR, ETLRow, CommitSummary)
3. **Implement checkpoint system** where appropriate in `app/summarize/`
4. **Use space-separated CSV column names** (`"commit hash"` not `"commit_hash"`)
5. **Handle diff truncation** with limits: 15000 per commit, 8000 per file

## Agent Responsibilities

### Development Agents
- Always run `make install` before starting work
- Review existing documentation in `/home/vscode/workspace/app/` first
- Use `make lint` and `make format-check` before committing changes
- Refer to prompt templates in `app/summarize/PROMPT.md`, `FILE_SUMMARY_PROMPT.md`, `COMMIT_SYNTHESIS_PROMPT.md`

### Testing Agents
- Run `make test` to verify all tests pass
- Add tests to `tests/<module_name>_test.py` following existing patterns
- Use test fixtures from `tests/git_data/resources/` for mocking data
- Tests do not require LLM API keys (mocked)

### Environment Agents
- Always verify `.env` file contains required variables
- LM Studio local inference uses `http://host.docker.internal:1234/v1` in Docker/devcontainer

## Architecture Documentation System

Refer to `/home/vscode/workspace/.opencode/architect/ARCHITECT_SKILL.yaml` for the code architect skill definition.

Available tools for maintaining documentation:
- **Code Architect** skill (`.opencode/architect/`) — reviews codebase and creates architecture.md files
- **System summary**: `.opencode/architect/architecture-summary.md`
- **Module docs**: `app/docs/<module>_architecture.md`

See `.opencode/architect/SUMMARY.txt` for detailed usage instructions.
