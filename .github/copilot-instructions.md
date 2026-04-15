# Project Guidelines

ETL pipeline that extracts git diffs and commit/PR messages from Minecraft repositories, generates LLM-powered semantic summaries, and outputs enriched CSVs.

## Build and Test

Use `make` targets — do not call Poetry or pytest directly:

- `make install` — install all dependencies (Poetry, in-project `.venv`)
- `make test` — run pytest with verbose output
- `make lint` — pylint on `llm-explore` and `tests/`
- `make format` — apply Black formatting
- `make format-check` — verify formatting without changes

When running Python directly, activate `.venv` first. Add new dependencies to `pyproject.toml`, not via `pip install`.

## CLI Entry Points

Three registered Poetry scripts:

| Command | Module | Purpose |
|---------|--------|---------|
| `etl-pipeline` | `app.etl_pipeline:main` | Full extraction + transform pipeline |
| `summarize-commits` | `app.summarize.summarize_commits:main` | LLM semantic summary generation |
| `run-notebook` | `app.notebooks.run_notebook:main` | Programmatic notebook execution |

Run via `poetry run <command>` or activate the venv first.

## Architecture

```
app/git_data/       → Extract: clone repos, extract commits (GitPython) & PRs (GitHub API)
app/git_data/       → Transform: parse repo IDs, match commits↔PRs, split diffs by file
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

Requires a `.env` file (not committed) with:
- `GOOGLE_API_KEY` — for Gemini API access
- `GEMINI_MODEL` — model name (default: `gemini-1.5-pro`)

Optional: `CHECKPOINT_DIR`, `MAX_RETRIES`, `TIMEOUT_SECONDS`, `LOG_LEVEL`

LM Studio local inference available via `http://host.docker.internal:1234/v1` (Docker/devcontainer only).

## Testing

- Tests use `pytest` with mocked LLM calls — no API keys needed for tests
- Test fixtures for diffs in `tests/git_data/resources/`
- One test file per module (e.g. `tests/test_commit_summarizer.py` ↔ `app/summarize/commit_summarizer.py`)

## Key Documentation

- [app/git_data/etl-plan.md](../app/git_data/etl-plan.md) — ETL pipeline design decisions
- [app/summarize/SUMMARIZER_IMPLEMENTATION.md](../app/summarize/SUMMARIZER_IMPLEMENTATION.md) — Summarizer architecture and checkpoint system
- Prompt templates: [PROMPT.md](../app/summarize/PROMPT.md), [FILE_SUMMARY_PROMPT.md](../app/summarize/FILE_SUMMARY_PROMPT.md), [COMMIT_SYNTHESIS_PROMPT.md](../app/summarize/COMMIT_SYNTHESIS_PROMPT.md)
