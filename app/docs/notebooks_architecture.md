# Notebooks Module Architecture

## Overview

The `notebooks` module provides utility functions for executing Jupyter notebooks programmatically and contains analysis notebooks that explore the ETL output and summaries. This enables exploratory data analysis (EDA), debugging, and ad-hoc investigation of commit summaries and other pipeline outputs.

### Module Location
```
app/notebooks/
├── run_notebook.py      # Jupyter notebook execution utility
└── summary_analysis.py  # Analysis notebook source code (Markdown + Python)
```

### Module Responsibilities
- Programmatic execution of Jupyter notebooks
- Generate executed notebook outputs (`.ipynb` files)
- Provide analysis templates for investigating summaries, finding points of interest

---

## Data Structures (Pydantic Models)

None. This module does not define Pydantic models.

---

## Entry Points and CLI Interfaces

### Poetry Script: `run-notebook`
CLI entry point registered in project root's `pyproject.toml`:

```toml
[tool.poetry.scripts]
run-notebook = "app.notebooks.run_notebook:main"
```

**Usage:**
```bash
poetry run run-notebook <notebook_path>

# Examples:
poetry run run-notebook app/notebooks/summary_analysis.py
# Generates: app/notebooks/summary_analysis_executed.ipynb
```

### Main Function Location
`app/notebooks/run_notebook.py::main()` → executes notebook and saves output

---

## Dependencies

### External Services
1. **nbformat** — Jupyter notebook I/O (reading/writing `.ipynb`)
2. **nbconvert** — Notebook execution (`ExecutePreprocessor`)

### Standard Library Imports
- `sys` — Command-line argument parsing

### Key Configuration
```python
# In run_notebook.py:main()
ep = ExecutePreprocessor(timeout=600, kernel_name='python3')
```
- **Timeout:** 600 seconds (10 minutes) per notebook cell
- **Kernel:** Python 3

---

## Key Algorithms and Logic

### Notebook Execution (`run_notebook.py`)
```python
def main():
    """Execute a Jupyter notebook and save output."""
    
    # 1. Parse arguments
    if len(sys.argv) < 2:
        print("Usage: poetry run run-notebook <notebook_path>")
        sys.exit(1)
    
    notebook_path = sys.argv[1]
    
    # 2. Read notebook as Python script (MARKDOWN comments work like regular Markdown)
    with open(notebook_path) as f:
        nb = nbformat.read(f, as_version=4)
    
    # 3. Execute using nbconvert's ExecutePreprocessor
    ep = ExecutePreprocessor(timeout=600, kernel_name='python3')
    ep.preprocess(nb, {'metadata': {'path': '.'}})
    
    # 4. Write executed notebook with outputs preserved
    output_path = notebook_path.replace('.py', '_executed.ipynb')
    with open(output_path, 'w') as f:
        nbformat.write(nb, f)
    
    print(f"Executed notebook saved to: {output_path}")
```

**Features:**
- Supports Jupyter Magic commands (`%md`, `# MAGIC`) for Markdown headers
- Preserves all cell outputs in generated `.ipynb`
- Creates sidecar executed versions for sharing

---

### Analysis Notebook: `summary_analysis.py`

This notebook explores differences between identical prompts + LLMs running on the same commits, identifying points of interest (POIs) where summaries differ significantly.

#### Purpose
Find variations in commit summary generation between datasets/LLMs to understand:
1. Where summaries diverge
2. Patterns affecting consistency
3. Areas needing prompt refinement or model adjustments

---

### Step 1: Data Loading

```python
# Load summaries from CSV (generated from partitioned Parquet)
df = pd.read_csv('../summaries/experiment-01-03-26/summaries.csv')

print(f"DataFrame shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")
```

**Schema:**
```python
Index(['Repo ID', 'commit hash', 'commit message', 'diff', 'PR message',
       'PR ID', 'semantic_summary'],
      dtype='str')
```

---

### Step 2: Bigram Extraction and Encoding

```python
from sklearn.feature_extraction.text import CountVectorizer

def get_bigrams(text):
    """Extract bigrams from text."""
    if pd.isna(text):
        return []
    vectorizer = CountVectorizer(ngram_range=(2, 2))
    try:
        vectorizer.fit([text])
        return vectorizer.get_feature_names_out()
    except Exception:
        return []

# Apply to all summaries
df['bigrams'] = df['semantic_summary'].apply(get_bigrams)
```

**Purpose:** Convert text summaries into bag-of-words representation using 2-word phrases (bigrams).

---

### Step 3: Vector Encoding with MultiLabelBinarizer

```python
from sklearn.preprocessing import MultiLabelBinarizer

mlb = MultiLabelBinarizer()
# Transform list of bigrams into binary matrix
bigram_matrix = mlb.fit_transform(df['bigrams'])
# Convert to DataFrame with column names from vocabulary
bigram_df = pd.DataFrame(bigram_matrix, columns=mlb.classes_, index=df.index)
```

**Purpose:** Create a sparse matrix where columns are unique bigrams and rows are summaries.

---

### Step 4: Compute Pairwise Distances

```python
from scipy.spatial.distance import cdist
import numpy as np

def calculate_distances(matrix, metric='cosine'):
    """Compute pairwise distance matrix."""
    distances = cdist(matrix, matrix, metric=metric)
    return pd.DataFrame(distances, index=df.index, columns=df.index)

# Compute using multiple metrics
cosine_distances = calculate_distances(bigram_matrix, 'cosine')
euclidean_distances = calculate_distances(bigram_matrix, 'euclidean')
```

**Metrics Supported:**
- `cosine` — Angular similarity between vectors (0 = different direction, 1 = identical)
- `euclidean` — Straight-line distance through vector space  
- Other valid scipy distances: `manhattan`, `jensenshannon`, etc.

---

### Step 5: Distance Ranking

```python
# Get upper triangle indices to avoid duplicates (only compare each pair once)
upper_triangle = np.triu_indices(len(df), k=1)

cosine_ranking = []
for i, j in zip(upper_triangle[0], upper_triangle[1]):
    cosine_ranking.append({
        'index_i': i,
        'index_j': j,
        'distance': cosine_distances.iloc[i, j],
        'summary_i': df.iloc[i]['semantic_summary'],
        'summary_j': df.iloc[j]['semantic_summary']
    })

cosine_ranking_df = pd.DataFrame(cosine_ranking).sort_values('distance', ascending=False)
```

**Purpose:** Create ranked list of summary pairs, highest distances first (most different).

---

### Points of Interest Analysis

Top-ranked differences indicate potential issues:
1. Same commit → completely different summaries
2. Similar commits → subtly different interpretations  
3. Dataset-specific quirks in prompt or model output

**Analysis Patterns:**
- Compare same git commit across different models/temperature settings
- Investigate whether distance correlates with semantic meaning
- Identify edge cases where LLM diverges significantly

---

## Module Interaction Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                                 notebooks                            │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    run_notebook.py                           │    │
│  │                                                              │    │
│  │  CLI Entry Point:                                            │    │
│  │    • Registered as 'run-notebook' in pyproject.toml          │    │
│  │    • Usage: poetry run run-notebook <py>                     │    │
│  └─────────────────────────────────┬───────────────────────────┘    │
│                                    │                                 │      External      │
│                 Jupyter Magic       │              Libraries          │     (NBConvert)    │
│                 Commands            │                                  │                  │
│           # MAGIC %md               ▼                                  │                  │
│         # MAGIC %matplotlib inline                                     │                  │
│                │                                                        │                  │
│         Notebook Source File                                            │                  │
│       (summary_analysis.py or .pyb)                                      │                  │
│                                                                            │                  │
│     ┌──────────▼─────────────────────────────────────────────────┐      │                  │
│     │           summary_analysis.py (Notebook Source)             │      │                  │
│     │                                                             │      │                  │
│     │   Structure: Markdown cells interleaved with Python        │      │                  │
│     │                                                            │      │                  │
│     │   Step 1: Load CSV → DataFrame                             │      │                  │
│     │   Step 2: Extract bigrams (CountVectorizer)                 │      │                  │
│     │   Step 3: Vector encoding (MultiLabelBinarizer)            │      │                  │
│     │   Step 4: Distance calculation (scipy.spatial.distance)     │      │                  │
│     │   Step 5: Ranking outputs                                   │      │                  │
│     │   Final: Display top differences                            │      │                  │
│     └──────────┬─────────────────────────────────────────────────┘      │                  │
│                │                                                        │                  │
│    Generated Output: summary_analysis_executed.ipynb                     │                  │
│                │                                                        │                  │
│         Jupyter Notebook with all cell outputs preserved                 │                  │
│                                                                            │                  │
└─────────────────────────────────────────────────────────────────────┘      │                  │
                                                                               └──────────┤
                                                                                          │
                                                    Input: CSV/Parquet from Summaries      │
                                                    Output: Executed Notebook (.ipynb)   │
                                                                                          │
┌─────────────────────────────────────────────────────────────────────────────┐           │
│                        Summary Pipeline                                     │             │
│                                                                            │             │
│  ┌─────────────────┐     ┌───────────────────┐     ┌─────────────────┐      │             │
│  │   ETL Pipeline  │────►│ git_data Parquet  │────►│ Summaries CSV / │      │             │
│  │                 │     │                    │     │ Partitioned PQ  │      │             │
│  └─────────────────┘     └───────────────────┘     └─────────────────┘      │             │
│                        │                                                   │             │
│   Intermediate: Raw commits + diffs                                        │             │
│                        │                                                   │             │
│                  External LLM API Call                                      │             │
│                                                ▼                                    │             │
│                                      Summarized output with semantic_summary column         │             │
└─────────────────────────────────────────────────────────────────────────────┘           │

