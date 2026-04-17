# Change ETL Pipeline Output Destination to $DB_PATH/git_data

## Current State
- File: `/home/vscode/workspace/app/git_data/etl_pipeline.py`
- Line 238: `write_to_csv` uses hardcoded filename `"commits_prs_output.csv"`
- Line 266: No parent directory creation before writing
- No environment variable support for output path

## Required Changes

### File: etl_pipeline.py (lines 1-10)
Add import and define output path:
```python
import os
from app.git_data.extract_git_data import extract_all_repos

# Output destination using DB_PATH environment variable
OUTPUT_DIR = f"{os.environ.get('DB_PATH', '/var/db')}/git_data"
```

### File: etl_pipeline.py (lines 232-254) - Modify write_to_csv function
Replace `write_to_csv` with signature and implementation:
```python
def write_to_csv(rows: List[ETLRow]) -> None:
    """
    Write ETL rows to CSV file.
    
    Args:
        rows: List of ETLRow objects to write
    """
    if not rows:
        print("No rows to write.")
        return
    
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    fieldnames = ["Repo ID", "commit hash", "commit message", "diff", "PR message", "PR ID"]
    
    output_file = os.path.join(OUTPUT_DIR, "commits_prs_output.csv")
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            row_dict = row.model_dump(by_alias=True)
            writer.writerow(row_dict)
    
    print(f"Wrote {len(rows)} rows to {output_file}")
```

### Run Command (after changes)
```bash
DB_PATH=/var/db etl-pipeline
# or
python -m app.git_data.etl_pipeline
```

## Expected Output Location
- Default: `/var/db/git_data/commits_prs_output.csv`
- Configurable via `DB_PATH` environment variable (e.g., in docker-compose)
