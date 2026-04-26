# Utils Module Architecture

## Overview

The `utils` module contains shared utility functions and classes used across other modules. Currently, it consists primarily of a logging configuration that provides consistent logging behavior throughout the application.

### Module Location
```
app/utils/
└── logging.py          # Central logger configuration
```

### Module Responsibilities
- Provide centralized logging infrastructure
- Configure log level from environment variable (`LOG_LEVEL`)
- Export `LOGGER` singleton instance for use across modules

---

## Code Structure

### `logging.py`
```python
import os
import logging

# Configure the logger
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
)
LOGGER = logging.getLogger("modder_mc_service")
LOGGER.setLevel(LOG_LEVEL)
```

---

## Pydantic Models

None. This module does not use Pydantic models.

---

## Dependencies

### Standard Library
- `os` — Environment variable access (`LOG_LEVEL`)
- `logging` — Python standard library logging

### External Dependencies
None. The logging module is completely self-contained.

---

## Entry Points

None. This is a support library, not a CLI entry point.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging verbosity level: DEBUG, INFO, WARNING, ERROR |

#### Usage Across Application:
```python
from app.utils.logging import LOGGER

LOGGER.info("This is an info message")
LOGGER.debug("Debug details (only shown if LOG_LEVEL=DEBUG)")
LOGGER.warning("Something unexpected happened")
LOGGER.error("An error occurred")
```

---

## Module Interaction Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        app/utils/                                │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │                logging.py                                  │   │
│  │                                                            │   │
│  │  Singleton Instance: LOGGER                                │   │
│  │    • Name: "modder_mc_service"                              │   │
│  │    • Level: LOG_LEVEL (from env)                            │   │
│  │    • Format: "%(asctime)s - %(levelname)s - %(message)s"%   │   │
│  └─────────────────────────┬──────────────────────────────────┘   │
│                            │                                       │
│                    Used by multiple modules                        │
│                                                            Uses:    │
│        ↓                                                        ↑   │
│  ┌─────▼─────┐                              Configuration       │
│  │ git_data/ │                              (LOG_LEVEL env var)  │
│  │          │                                                  │
│  ├──────────┤     app/git_data/*.py                                │
│  │          │    etl_pipeline.py                                   │
│  │          │    extract_git_data.py                               │
│  ├──────────┤    extract_pr_data.py                                │
│  │          │                                                  │   │
│  ┌─────▼─────┐                              (None required)        │
│  │ summarize/ │    app/summarize/*.py                             │
│  │           │    commit_summarizer.py                            │
│  ├───────────┤    summarize_commits.py                            │   │
│  │           │    summarizer_config.py                            │
│  └───────────┘                                                  │     │
│                                                                  │     │
|          app/summarize/*.py                                    │
│              load_summaries.py                                 │
│                (app/vectordb/*)                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## Design Patterns Used

### Singleton Pattern
The `LOGGER` instance is initialized at module load time and reused globally:

```python
# In app/utils/logging.py:
LOGGER = logging.getLogger("modder_mc_service")

# Usage anywhere in app/:
from app.utils.logging import LOGGER

LOGGER.info(f"Processing commit {commit_hash[:8]}...")
```

### Environment Configuration Pattern
Log level is configurable via environment variable, allowing runtime adjustment without code changes:

```bash
# Set log level before running any poetry command
export LOG_LEVEL=DEBUG
poetry run etl-pipeline    # Will output DEBUG messages

export LOG_LEVEL=INFO
poetry run summarize-commits   # Normal info-level logging
```

---

## Logging Best Practices in This Application

### 1. Consistent Context
All log messages include meaningful context (repo IDs, commit hashes):

```python
LOGGER.info(f"Processing commit {i}/{total_commits}: {commit_hash[:8]}...")
LOGGER.warning(f"File diff truncated from {orig_length} to {max_chars} chars")
LOGGER.error(f"✗ Failed to summarize {commit_hash[:8]}: {e}")
```

### 2. Proper Log Levels
- `DEBUG` — Detailed diagnostics, chunking decisions, retry counts
- `INFO` — Success notifications, completion messages, checkpoint resume notices
- `WARNING` — Recoverable issues (truncation, retries, already-exist)
- `ERROR` — Unexpected failures, permanent errors

### 3. Error Context
Error logs include:
- Commit hash prefix for identification
- Original exception via stacktrace formatting (`from e`)

```python
except Exception as e:
    LOGGER.error(f"✗ Failed to summarize {commit_hash[:8]}: {e}")
```

---

## Extending the Logging Module (Future Enhancement)

The current implementation is minimal. Future extension could include:

```python
# app/utils/logging.py (enhanced)
import os
import logging
from typing import Optional
from contextvars import ContextVar

# Current module-level singleton
LOGGER = logging.getLogger("modder_mc_service")

# Future additions:
# - Add structured logging support (JSON for production, text for dev)
# - Add request correlation IDs
# - Support log rotation in larger deployments
# - Add tracing/exporting to external systems (optional)
```

---

## CLI Entry Point Registration (pyproject.toml)

None. This module is not a standalone CLI entry point.

---

## Testing Pattern

Located in `tests/utils/`:
- Tests for environment variable handling
- Logs output can be captured and verified
- Can test custom log level configurations

Example test:
```python
def test_logging_level_from_env(monkeypatch, caplog):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    from app.utils.logging import LOGGER
    with caplog.at_level(logging.DEBUG):
        LOGGER.debug("This should appear in DEBUG log")
        assert "This should appear" in caplog.text


def test_logging_level_default(monkeypatch, capwarn):
    monkeypatch.delenv("LOG_LEVEL", raising=False)  # Use default
    from app.utils.logging import LOGGER
    with caplog.at_level(logging.WARNING):
        LOGGER.debug("Should NOT appear")
        LOGGER.info("Info level message")
        assert "debug" not in caplog.text.lower()
        assert "info" in caplog.text.lower()
```

