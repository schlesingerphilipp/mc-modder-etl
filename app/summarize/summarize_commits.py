"""Standalone CLI entry point for commit summarization.

Usage:
    etl-summarize-commits input_csv output_csv [--checkpoint-dir DIR]
    
Example:
    etl-summarize-commits commits_prs_output.csv commits_with_summaries.csv
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from app.summarize.summarizer_config import SummarizerConfig
from app.summarize.commit_summarizer import CommitSummarizer, compute_csv_hash
from app.utils.logging import LOGGER

def validate_csv(file_path: Path) -> pd.DataFrame:
    """Validate and load CSV file.
    
    Args:
        file_path: Path to CSV file
    
    Returns:
        Loaded DataFrame
    
    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If CSV is invalid or missing required columns
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {file_path}")
    
    df = pd.read_csv(file_path)
    
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
        description="Generate semantic summaries of commits using Google Gemini"
    )
    parser.add_argument(
        "input_csv",
        type=Path,
        help="Path to input ETL CSV file"
    )
    parser.add_argument(
        "output_csv",
        type=Path,
        help="Path to output CSV file with semantic summaries"
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=Path(".checkpoints/summarize"),
        help="Directory for checkpoint files (default: from .env or ./checkpoints/summarize)"
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
        
        # Validate input CSV
        LOGGER.info(f"Loading input CSV: {args.input_csv}")
        df = validate_csv(args.input_csv)
        LOGGER.info(f"Loaded {len(df)} rows from {df['commit hash'].nunique()} commits")
        
        # Load configuration
        LOGGER.info(f"Loading summarizer configuration... with checkpoint dir: {args.checkpoint_dir}")
        config = SummarizerConfig(checkpoint_dir=args.checkpoint_dir)
        LOGGER.info(f"Checkpoint directory: {config.checkpoint_dir}")
        
        # Compute CSV hash for checkpoint tracking
        csv_hash = compute_csv_hash(args.input_csv)
        LOGGER.info(f"CSV hash for checkpoint tracking: {csv_hash}")
        
        # Initialize summarizer
        LOGGER.info("Initializing Gemini API client...")
        summarizer = CommitSummarizer(config)
        
        # Process commits with checkpoints
        LOGGER.info("Processing commits with checkpoint-based resumption...")
        df_with_summaries, checkpoint = summarizer.process_commits(df, csv_hash)
        
        # Save output
        LOGGER.info(f"Writing output CSV: {args.output_csv}")
        df_with_summaries.to_csv(args.output_csv, index=False)
        
        # Log summary
        LOGGER.info("=" * 60)
        LOGGER.info(f"✓ Processing complete!")
        LOGGER.info(f"  • Processed commits: {len(checkpoint.processed_commits)}")
        LOGGER.info(f"  • Failed commits: {len(checkpoint.failed_commits)}")
        LOGGER.info(f"  • Output file: {args.output_csv}")
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
