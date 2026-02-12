"""Commit summarizer using Google Gemini API with checkpoint-based resumption."""

import json
import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict

import pandas as pd
from langchain_google_genai import ChatGoogleGenerativeAI

from app.summarizer_config import SummarizerConfig
from app.models import CommitSummary

logger = logging.getLogger(__name__)


@dataclass
class CheckpointData:
    """Data structure for checkpoint persistence."""
    processed_commits: Dict[str, str]  # commit_hash -> semantic_summary
    failed_commits: Dict[str, str]  # commit_hash -> error_message
    total_commits: int


class CheckpointManager:
    """Manages checkpoint saving and loading for resumable processing."""
    
    def __init__(self, checkpoint_path: Path):
        """Initialize checkpoint manager.
        
        Args:
            checkpoint_path: Path to store checkpoint file
        """
        self.checkpoint_path = checkpoint_path
    
    def load(self) -> Optional[CheckpointData]:
        """Load checkpoint if it exists.
        
        Returns:
            CheckpointData if checkpoint exists, None otherwise
        """
        if not self.checkpoint_path.exists():
            return None
        
        try:
            with open(self.checkpoint_path, "r") as f:
                data = json.load(f)
            return CheckpointData(**data)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None
    
    def save(self, checkpoint: CheckpointData) -> None:
        """Save checkpoint.
        
        Args:
            checkpoint: CheckpointData to save
        """
        try:
            with open(self.checkpoint_path, "w") as f:
                json.dump(asdict(checkpoint), f, indent=2)
            logger.info(f"Checkpoint saved: {self.checkpoint_path}")
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")
            raise


class CommitSummarizer:
    """Summarizes commits using Google Gemini API."""
    
    def __init__(self, config: SummarizerConfig):
        """Initialize the summarizer.
        
        Args:
            config: SummarizerConfig instance
        """
        self.config = config
        self.client = ChatGoogleGenerativeAI(
            model=config.gemini_model,
            google_api_key=config.google_api_key,
            temperature=0.3,  # Lower temperature for more focused summaries
        )
    
    def group_rows_by_commit(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Group ETL rows by commit hash.
        
        Args:
            df: DataFrame from ETL output CSV
        
        Returns:
            Dictionary mapping commit_hash to group DataFrame
        """
        return {commit_hash: group for commit_hash, group in df.groupby("commit hash")}
    
    def combine_commit_diffs(self, group: pd.DataFrame) -> str:
        """Combine all diffs from a commit group.
        
        Args:
            group: DataFrame group for a single commit
        
        Returns:
            Combined diff string with file separators
        """
        diffs = []
        for idx, row in group.iterrows():
            diff = row.get("diff", "")
            if diff and diff.strip():
                diffs.append(diff)
        
        # Join with clear file separators
        return "\n\n--- FILE SEPARATOR ---\n\n".join(diffs)
    
    def create_semantic_prompt(self, commit_message: str, combined_diffs: str) -> str:
        """Create a semantic analysis prompt.
        
        Args:
            commit_message: Original commit message
            combined_diffs: Combined diffs from all files in commit
        
        Returns:
            Formatted prompt for Gemini API
        """
        return self.config.semantic_prompt_template.format(
            commit_message=commit_message,
            combined_diffs=combined_diffs
        )
    
    def summarize_with_gemini(self, prompt: str) -> str:
        """Call Gemini API to generate semantic summary.
        
        Args:
            prompt: Prompt to send to Gemini
        
        Returns:
            Generated summary
        
        Raises:
            Exception: If API call fails after retries
        """
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.invoke(prompt)
                return response.content
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    logger.warning(f"Gemini API call failed (attempt {attempt + 1}): {e}")
        
        logger.error(f"Gemini API call failed after {self.config.max_retries} attempts")
        raise Exception(f"Gemini API call failed after {self.config.max_retries} attempts") from last_error
    
    def process_commits(
        self,
        df: pd.DataFrame,
        csv_hash: str
    ) -> tuple[pd.DataFrame, CheckpointData]:
        """Process commits and generate summaries with checkpoint support.
        
        Args:
            df: DataFrame from ETL output CSV
            csv_hash: Hash of CSV file for checkpoint tracking
        
        Returns:
            Tuple of (updated DataFrame with summaries, checkpoint data)
        
        Raises:
            Exception: If processing fails (aborts on error for checkpoint-based recovery)
        """
        checkpoint_manager = CheckpointManager(self.config.get_checkpoint_file(csv_hash))
        checkpoint = checkpoint_manager.load()
        
        # Initialize checkpoint data
        if checkpoint:
            processed_commits = checkpoint.processed_commits
            failed_commits = checkpoint.failed_commits
            total_commits = checkpoint.total_commits
            logger.info(f"Resuming from checkpoint: {len(processed_commits)} processed, "
                       f"{len(failed_commits)} failed")
        else:
            processed_commits = {}
            failed_commits = {}
            total_commits = df["commit hash"].nunique()
        
        # Group rows by commit
        commit_groups = self.group_rows_by_commit(df)
        
        # Process each commit
        for i, (commit_hash, group) in enumerate(commit_groups.items(), 1):
            # Skip if already processed
            if commit_hash in processed_commits:
                logger.debug(f"Skipping already processed commit: {commit_hash}")
                continue
            
            if commit_hash in failed_commits:
                logger.debug(f"Skipping previously failed commit: {commit_hash}")
                continue
            
            try:
                logger.info(f"Processing commit {i}/{total_commits}: {commit_hash[:8]}...")
                
                # Get commit message (same for all rows in group)
                commit_message = group.iloc[0]["commit message"]
                
                # Combine diffs
                combined_diffs = self.combine_commit_diffs(group)
                
                # Create prompt
                prompt = self.create_semantic_prompt(commit_message, combined_diffs)
                
                # Generate summary
                summary = self.summarize_with_gemini(prompt)
                
                # Save to checkpoint
                processed_commits[commit_hash] = summary
                checkpoint_data = CheckpointData(
                    processed_commits=processed_commits,
                    failed_commits=failed_commits,
                    total_commits=total_commits
                )
                checkpoint_manager.save(checkpoint_data)
                
                logger.info(f"✓ Summary generated for {commit_hash[:8]}")
                
            except Exception as e:
                logger.error(f"✗ Failed to summarize {commit_hash[:8]}: {e}")
                failed_commits[commit_hash] = str(e)
                
                # Save checkpoint before aborting
                checkpoint_data = CheckpointData(
                    processed_commits=processed_commits,
                    failed_commits=failed_commits,
                    total_commits=total_commits
                )
                checkpoint_manager.save(checkpoint_data)
                
                # Abort on error for checkpoint-based recovery
                raise Exception(
                    f"Processing failed at commit {commit_hash[:8]}. "
                    f"Checkpoint saved. Run again to resume from this point."
                ) from e
        
        # Add summaries to dataframe
        def get_summary(commit_hash: str) -> Optional[str]:
            """Get summary for a commit hash."""
            return processed_commits.get(commit_hash)
        
        df["semantic_summary"] = df["commit hash"].apply(get_summary)
        
        # Final checkpoint
        final_checkpoint = CheckpointData(
            processed_commits=processed_commits,
            failed_commits=failed_commits,
            total_commits=total_commits
        )
        checkpoint_manager.save(final_checkpoint)
        
        return df, final_checkpoint


def compute_csv_hash(file_path: Path) -> str:
    """Compute hash of CSV file for checkpoint tracking.
    
    Args:
        file_path: Path to CSV file
    
    Returns:
        SHA256 hash of file
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()[:16]
