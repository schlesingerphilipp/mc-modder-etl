"""Standalone CLI entry point for commit summarization.

Usage:
    summarize-commits input_file output_file [--checkpoint-dir DIR]
    
Example:
    summarize-commits commits_prs_output.parquet commits_with_summaries.parquet
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from app.summarize.summarizer_config import SummarizerConfig
from app.summarize.commit_summarizer import CommitSummarizer, compute_file_hash
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
        description="Generate semantic summaries of commits using Google Gemini"
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to input ETL Parquet file"
    )
    parser.add_argument(
        "output_file",
        type=Path,
        help="Path to output Parquet file with semantic summaries"
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
        
        # Validate input
        LOGGER.info(f"Loading input: {args.input_file}")
        df = validate_input(args.input_file)
        LOGGER.info(f"Loaded {len(df)} rows from {df['commit hash'].nunique()} commits")
        
        # Load configuration
        LOGGER.info(f"Loading summarizer configuration... with checkpoint dir: {args.checkpoint_dir}")
        config = SummarizerConfig(checkpoint_dir=args.checkpoint_dir)
        LOGGER.info(f"Checkpoint directory: {config.checkpoint_dir}")
        
        # Compute file hash for checkpoint tracking
        file_hash = compute_file_hash(args.input_file)
        LOGGER.info(f"Input hash for checkpoint tracking: {file_hash}")
        
        # Initialize summarizer
        LOGGER.info("Initializing LLM client...")
        summarizer = CommitSummarizer(config)
        
        # Process commits with checkpoints
        LOGGER.info("Processing commits with checkpoint-based resumption...")
        df_with_summaries, checkpoint = summarizer.process_commits(df, file_hash, args.output_file)
        
        # Save output
        LOGGER.info(f"Writing output: {args.output_file}")
        args.output_file.parent.mkdir(parents=True, exist_ok=True)
        df_with_summaries.to_parquet(args.output_file, index=False)
        
        # Log summary
        LOGGER.info("=" * 60)
        LOGGER.info(f"✓ Processing complete!")
        LOGGER.info(f"  • Processed commits: {len(checkpoint.processed_commits)}")
        LOGGER.info(f"  • Failed commits: {len(checkpoint.failed_commits)}")
        LOGGER.info(f"  • Output file: {args.output_file}")
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
