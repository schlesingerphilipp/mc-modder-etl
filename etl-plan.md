## Plan: ETL Pipeline for Git Commits, PRs, and Diffs

Build an ETL pipeline that extracts commits and PRs, matches them by parsing commit hashes from PR descriptions, and outputs a CSV with repo ID, commit hash, message, diff, PR message, and PR ID (null if no PR).

### Steps

1. **Create a `match_commits_to_prs()` function** in a new module (e.g., [app/etl_pipeline.py](app/etl_pipeline.py)) that:
   - Takes commit data and PR data as input
   - Searches PR body/title text for commit hashes (via regex: [0-9a-f]{7,40})
   - Returns a mapping of commit_hash → PR data

2. **Create a `parse_repo_id()` function** that extracts owner/repo from the full GitHub URL (e.g., `https://github.com/TheGreyGhost/MinecraftByExample` → `TheGreyGhost/MinecraftByExample`).

3. **Create an `extract_and_transform()` orchestration function** that:
   - Calls existing `extract_all_commits()` from [app/extract_git_data.py](app/extract_git_data.py)
   - Calls existing `extract_all_prs()` from [app/extract_pr_data.py](app/extract_pr_data.py)
   - Matches commits to PRs using `match_commits_to_prs()`
   - Builds rows with all required columns including null PR fields for unmatched commits

4. **Create a `write_to_csv()` function** that writes the combined data to CSV with columns: "Repo ID", "commit hash", "commit message", "diff", "PR message", "PR ID".

5. **Integrate into** [app/main.py](app/main.py) to orchestrate the full pipeline on execution.

6. **Add tests** in [tests/test_extract_git_data.py](tests/test_extract_git_data.py) (or new test file) validating:
   - Commit-PR matching logic
   - CSV output structure and null handling
   - Repo ID parsing

### Further Considerations

1. **What CSV output filename should we use?** Option A: `commits_prs_output.csv` / Option B: Timestamp-based name (e.g., `commits_prs_2026_02_11.csv`) / Option C: Configurable via environment variable

2. **Should we deduplicate rows** if the same commit appears in multiple PRs, or keep all matches?

3. **For commit hash matching in PR text, should we** Option A: Match any 7+ character hex string / Option B: Match only full 40-character SHAs / Option C: Match both formats intelligently