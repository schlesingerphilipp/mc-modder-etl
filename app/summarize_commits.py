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

from app.summarizer_config import SummarizerConfig
from app.commit_summarizer import CommitSummarizer, compute_csv_hash


def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )


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
        default=None,
        help="Directory for checkpoint files (default: from .env or ./checkpoints)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("=" * 60)
        logger.info("Commit Semantic Summarizer")
        logger.info("=" * 60)
        
        # Validate input CSV
        logger.info(f"Loading input CSV: {args.input_csv}")
        df = validate_csv(args.input_csv)
        logger.info(f"Loaded {len(df)} rows from {df['commit hash'].nunique()} commits")
        
        # Load configuration
        logger.info("Loading summarizer configuration...")
        config = SummarizerConfig(checkpoint_dir=args.checkpoint_dir)
        logger.info(f"Using Gemini model: {config.gemini_model}")
        logger.info(f"Checkpoint directory: {config.checkpoint_dir}")
        
        # Compute CSV hash for checkpoint tracking
        csv_hash = compute_csv_hash(args.input_csv)
        logger.info(f"CSV hash for checkpoint tracking: {csv_hash}")
        
        # Initialize summarizer
        logger.info("Initializing Gemini API client...")
        summarizer = CommitSummarizer(config)
        
        # Process commits with checkpoints
        logger.info("Processing commits with checkpoint-based resumption...")
        df_with_summaries, checkpoint = summarizer.process_commits(df, csv_hash)
        
        # Save output
        logger.info(f"Writing output CSV: {args.output_csv}")
        df_with_summaries.to_csv(args.output_csv, index=False)
        
        # Log summary
        logger.info("=" * 60)
        logger.info(f"✓ Processing complete!")
        logger.info(f"  • Processed commits: {len(checkpoint.processed_commits)}")
        logger.info(f"  • Failed commits: {len(checkpoint.failed_commits)}")
        logger.info(f"  • Output file: {args.output_csv}")
        logger.info("=" * 60)
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(f"File error: {e}")
        return 1
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        logger.error("Run again with --verbose for more details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
