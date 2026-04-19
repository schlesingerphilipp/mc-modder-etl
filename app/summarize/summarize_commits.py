"""Standalone CLI entry point for commit summarization.

Usage:
    summarize-commits input_dir output_dir
    
Example:
    summarize-commits /var/db/git_data /var/db/summaries
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from app.summarize.summarizer_config import SummarizerConfig
from app.summarize.commit_summarizer import CommitSummarizer
from app.utils.logging import LOGGER

def validate_input(file_path: Path) -> pd.DataFrame:
    """Validate and load input Parquet file.
    
    Args:
        file_path: Path to input Parquet file or directory
    
    Returns:
        Loaded DataFrame
    
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If data is invalid or missing required columns
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Input file not found: {file_path}")
    
    df = pd.read_parquet(file_path)
    
    required_columns = ["commit hash", "commit message", "diff"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")
    
    return df


def main() -> int:
    """Main entry point for commit summarization.
    
    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Generate semantic summaries of commits using LLM"
    )
    parser.add_argument(
        "input_file",
        nargs="?",
        default=Path("/var/db/git_data"),
        type=Path,
        help="Path to input ETL Parquet file or directory (default: /var/db/git_data/)"
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=Path("/var/db/summaries"),
        type=Path,
        help="Path to output directory for partitioned Parquet (default: /var/db/summaries)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    args = parser.parse_args()
        
    try:
        LOGGER.info("=" * 60)
        LOGGER.info("Commit Semantic Summarizer")
        LOGGER.info("=" * 60)
        
        # Validate input
        LOGGER.info(f"Loading input: {args.input_file}")
        df = validate_input(args.input_file)
        LOGGER.info(f"Loaded {len(df)} rows from {df['commit hash'].nunique()} commits")
        
        # Load configuration
        config = SummarizerConfig()
        
        # Initialize summarizer
        LOGGER.info("Initializing LLM client...")
        summarizer = CommitSummarizer(config)
        
        # Process commits with incremental parquet output
        LOGGER.info(f"Processing commits, output dir: {args.output_dir}")
        counts = summarizer.process_commits(df, args.output_dir)
        
        # Log summary
        LOGGER.info("=" * 60)
        LOGGER.info(f"✓ Processing complete!")
        LOGGER.info(f"  • Processed: {counts['processed']}")
        LOGGER.info(f"  • Skipped (already exist): {counts['skipped']}")
        LOGGER.info(f"  • Failed: {counts['failed']}")
        LOGGER.info(f"  • Output dir: {args.output_dir}")
        LOGGER.info("=" * 60)
        
        return 0
        
    except FileNotFoundError as e:
        LOGGER.error(f"File error: {e}")
        return 1
    except ValueError as e:
        LOGGER.error(f"Validation error: {e}")
        return 1
    except Exception as e:
        LOGGER.error(f"Processing failed: {e}")
        LOGGER.error("Run again with --verbose for more details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
