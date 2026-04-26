# Code Architect Agent Instructions

## Purpose
Review the entire codebase under `app/` and create comprehensive architecture documentation that helps development assistants understand:
- System boundaries and responsibilities
- Data flows between modules
- Design patterns and conventions
- Integration points and dependencies

## Documentation Output

Create two types of markdown files:

### 1. per-module/architecture.md
Location: `<app_module>/../docs/<module_name>_architecture.md`

Each file should contain:
- **Module Overview** - Purpose and responsibilities
- **Data Structures** (if applicable) - Pydantic models, key classes  
- **Entry Points** - Functions that interface externally
- **Dependencies** - Imports and external services
- **Key Algorithms/Logic** - Core data transformations

### 2. architecture-summary.md
Location: `.opencode/architect/architecture-summary.md`

Contains:
- System-level overview
- Module interaction diagram (ASCII or Mermaid)
- Data flow description
- Architecture decisions recorded (ADRs)
- Design patterns in use

## Review Process

1. **Scan all files under `app/`** recursively
2. For each Python file:
   - Identify module boundary it serves
   - Extract Pydantic models for schema documentation
   - Document function signatures and purposes
   - Note external API integrations (GitHub, LLM APIs)
3. **Map dependencies** between modules
4. **Trace data flows** from input → transformation → output
5. **Document patterns** (e.g., "checkpoint resume", "CLI entry points")

## Data Flow Description Template

When documenting data flows:

```
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Extract     │ →  │   Transform   │ →  │  Summarize    │
│ (git_data)    │    │   (ETL+merge) │    │  (LLM)        │
└───────────────┘    └───────────────┘    └───────────────┘
        ↓                  ↓                     ↓
```

Describe each stage:
- **What data enters**: Repo list, commits, PRs
- **Transformations**: Parse, match, split diffs  
- **What leaves**: CSV files, enriched summaries
- **External services**: GitHub API, Gemini/LM Studio

## File Location Strategy

Module architectures → `app/docs/<module>_architecture.md`
- git_data_architecture.md
- summarize_architecture.md
- notebooks_architecture.md
- utils_architecture.md

System architecture → `.opencode/architect/architecture-summary.md`

## Style Guidelines

- Use ASCII diagrams (no external image dependencies)
- Reference other docs when describing modules
- Keep per-module files focused on that component
- System file shows integration points between components