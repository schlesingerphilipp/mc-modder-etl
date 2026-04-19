"""Commit summarizer using Google Gemini API with checkpoint-based resumption."""

import json
import hashlib
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from pydantic import BaseModel
import pandas as pd
from langchain_openai import ChatOpenAI

from app.summarize.summarizer_config import SummarizerConfig
from app.git_data.models import CommitSummary

from app.utils.logging import LOGGER

class CommitSummaryResult(BaseModel):
    """The summary of a commit diff"""
    semantic_summary: str


class FileSummaryResult(BaseModel):
    """The summary of a single file diff"""
    file_summary: str

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
            LOGGER.warning(f"Failed to load checkpoint: {e}")
            return None
    
    def save(self, checkpoint: CheckpointData) -> None:
        """Save checkpoint.
        
        Args:
            checkpoint: CheckpointData to save
        """
        try:
            with open(self.checkpoint_path, "w") as f:
                json.dump(asdict(checkpoint), f, indent=2)
            LOGGER.info(f"Checkpoint saved: {self.checkpoint_path}")
        except Exception as e:
            LOGGER.error(f"Failed to save checkpoint: {e}")
            raise


class CommitSummarizer:
    """Summarizes commits using Google Gemini API."""
    
    def __init__(self, config: SummarizerConfig):
        """Initialize the summarizer.
        
        Args:
            config: SummarizerConfig instance
        """
        self.config = config
        
        self.commit_client = ChatOpenAI(
            model=config.lmstudio_model,
            base_url=config.lmstudio_base_url,
            api_key=config.lmstudio_api_key,
            temperature=0
        )
        
        self.file_client = ChatOpenAI(
            model=config.lmstudio_model,
            base_url=config.lmstudio_base_url,
            api_key=config.lmstudio_api_key,
            temperature=0
        )
    
    def group_rows_by_commit(self, df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Group ETL rows by commit hash.
        
        Args:
            df: DataFrame from ETL output CSV
        
        Returns:
            Dictionary mapping commit_hash to group DataFrame
        """
        return {commit_hash: group for commit_hash, group in df.groupby("commit hash")}
    
    def summarize_file_diff(self, file_path: str, diff: str) -> str:
        """Summarize a single file's diff.
        
        Args:
            file_path: Path to the file
            diff: Diff content
        
        Returns:
            Summary of changes in this file
        
        Raises:
            Exception: If API call fails after retries
        """
        truncated = False
        if len(diff) > self.config.max_file_diff_length:
            orig_length = len(diff)
            diff = diff[:self.config.max_file_diff_length]
            truncated = True
            LOGGER.warning(
                f"File diff truncated from {orig_length} to {self.config.max_file_diff_length} chars "
                f"for {file_path} (MAX_FILE_DIFF_LENGTH)"
            )
        
        prompt = self.config.file_summary_prompt_template.format(
            file_path=file_path,
            diff=diff
        )
        
        if truncated:
            diff_for_prompt = diff + "\n\n[... DIFF TRUNCATED ...]"
            prompt = self.config.file_summary_prompt_template.format(
                file_path=file_path,
                diff=diff_for_prompt
            )
        
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = self.file_client.invoke(prompt)
                content = response.content.strip()
                LOGGER.debug(f"File LLM response: {content[:200]}")
                if not content:
                    raise ValueError("LLM returned empty content")
                parsed = json.loads(content)
                return parsed["file_summary"]
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    LOGGER.warning(f"File summary LLM call failed (attempt {attempt + 1}): {e}")
        
        LOGGER.error(f"File summary LLM call failed after {self.config.max_retries} attempts")
        raise Exception(f"File summary LLM call failed after {self.config.max_retries} attempts") from last_error
    
    def summarize_commit_files(self, commit_message: str, group: pd.DataFrame) -> List[Dict[str, str]]:
        """Summarize all files in a commit.
        
        Args:
            commit_message: Original commit message
            group: DataFrame group for a single commit
        
        Returns:
            List of dicts with file_path and summary
        """
        file_summaries = []
        
        for idx, row in group.iterrows():
            diff = row.get("diff", "")
            
            diff_str = str(diff).strip() if diff is not None else ""
            if not diff_str or diff_str.lower() in ("nan", "none"):
                LOGGER.debug(f"Skipping empty/null diff for file index {idx}")
                continue
            
            # Extract file path from diff header (e.g. "--- a/path/to/file.py")
            file_path = f"unknown_{idx}"
            for line in diff_str.splitlines():
                if line.startswith("--- a/"):
                    file_path = line[6:]
                    break
                if line.startswith("+++ b/"):
                    file_path = line[6:]
                    break
            
            try:
                LOGGER.debug(f"Summarizing file: {file_path}")
                summary = self.summarize_file_diff(file_path, diff_str)
                file_summaries.append({
                    "file": file_path,
                    "summary": summary
                })
            except Exception as e:
                LOGGER.warning(f"Failed to summarize file {file_path}: {e}")
                file_summaries.append({
                    "file": file_path,
                    "summary": "[Failed to summarize]"
                })
        
        return file_summaries
    
    def _invoke_synthesis(self, commit_message: str, formatted_summaries: str) -> str:
        """Invoke the synthesis LLM and parse the JSON response.
        
        Args:
            commit_message: Original commit message
            formatted_summaries: Pre-formatted file summaries string
        
        Returns:
            Semantic summary string
        
        Raises:
            Exception: If API call fails after retries
        """
        prompt = self.config.commit_synthesis_prompt_template.format(
            commit_message=commit_message,
            file_summaries=formatted_summaries
        )
        
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = self.commit_client.invoke(prompt)
                content = response.content.strip()
                LOGGER.debug(f"Commit LLM response: {content[:200]}")
                if not content:
                    raise ValueError("LLM returned empty content")
                parsed = json.loads(content)
                return parsed["semantic_summary"]
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    LOGGER.warning(f"Synthesis LLM call failed (attempt {attempt + 1}): {e}")
        
        LOGGER.error(f"Synthesis LLM call failed after {self.config.max_retries} attempts")
        raise Exception(f"Synthesis LLM call failed after {self.config.max_retries} attempts") from last_error

    def synthesize_commit_summary(self, commit_message: str, file_summaries: List[Dict[str, str]]) -> str:
        """Synthesize file summaries into a commit-level summary.
        
        When the combined file summaries exceed MAX_SYNTHESIS_LENGTH, splits them
        into chunks, summarizes each chunk, then synthesizes the chunk summaries.
        
        Args:
            commit_message: Original commit message
            file_summaries: List of file summaries
        
        Returns:
            Final commit-level semantic summary
        
        Raises:
            Exception: If API call fails after retries
        """
        if not file_summaries:
            return "No file changes to summarize."
        
        formatted_lines = [
            f"- {fs['file']}: {fs['summary']}" for fs in file_summaries
        ]
        return self.synthesize_summary_chunking(commit_message, formatted_lines)

    def synthesize_summary_chunking(self, commit_message: str, formatted_lines: list[str]) -> str:
        
        max_len = self.config.max_synthesis_length
        summary = "\n".join(formatted_lines)

        if len(summary) <= max_len:
            return self._invoke_synthesis(commit_message, summary)
        
        # Split into chunks that fit within max_len
        LOGGER.info(
            f"File summaries too large ({len(summary)} chars), "
            f"chunking at {max_len} chars"
        )
        chunks = []
        current_chunk = []
        current_len = 0
        for line in formatted_lines:
            line_len = len(line) + 1  # +1 for newline
            if current_len + line_len > max_len:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
                current_len = 0
            current_chunk.append(line)
            current_len += line_len

        if len(current_chunk) > 0:
            chunks.append("\n".join(current_chunk))
        
        LOGGER.info(f"Split into {len(chunks)} chunks for hierarchical synthesis")
        
        # Summarize each chunk
        chunk_summaries = []
        for i, chunk in enumerate(chunks, 1):
            LOGGER.debug(f"Synthesizing chunk {i}/{len(chunks)} ({len(chunk)} chars)")
            summary = self._invoke_synthesis(commit_message, chunk)
            chunk_summaries.append(summary)
        
        # Final synthesis from chunk summaries
        LOGGER.debug(f"Final synthesis from {len(chunk_summaries)} chunk summaries")
        return self.synthesize_summary_chunking(commit_message, chunk_summaries)
    
    def process_commits(
        self,
        df: pd.DataFrame,
        csv_hash: str,
        output_path: Path = None
    ) -> tuple[pd.DataFrame, CheckpointData]:
        """Process commits and generate summaries with checkpoint support.
        
        Args:
            df: DataFrame from ETL output CSV
            csv_hash: Hash of CSV file for checkpoint tracking
            output_path: Optional output CSV path to differentiate checkpoints
        
        Returns:
            Tuple of (updated DataFrame with summaries, checkpoint data)
        
        Raises:
            Exception: If processing fails (aborts on error for checkpoint-based recovery)
        """
        checkpoint_manager = CheckpointManager(self.config.get_checkpoint_file(csv_hash, output_path))
        checkpoint = checkpoint_manager.load()
        
        # Initialize checkpoint data
        if checkpoint:
            processed_commits = checkpoint.processed_commits
            failed_commits = checkpoint.failed_commits
            total_commits = checkpoint.total_commits
            LOGGER.info(f"Resuming from checkpoint: {len(processed_commits)} processed, "
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
                LOGGER.debug(f"Skipping already processed commit: {commit_hash}")
                continue
            
            if commit_hash in failed_commits:
                LOGGER.info(f"Retrying previously failed commit: {commit_hash[:8]}")
                del failed_commits[commit_hash]
            
            try:
                LOGGER.info(f"Processing commit {i}/{total_commits}: {commit_hash[:8]}...")
                
                # Get commit message (same for all rows in group)
                commit_message = group.iloc[0]["commit message"]
                
                # Summarize each file individually
                file_summaries = self.summarize_commit_files(commit_message, group)
                
                # Synthesize into final commit summary
                summary = self.synthesize_commit_summary(commit_message, file_summaries)
                LOGGER.debug(f"Generated summary {summary}")
                
                # Save to checkpoint
                processed_commits[commit_hash] = summary
                checkpoint_data = CheckpointData(
                    processed_commits=processed_commits,
                    failed_commits=failed_commits,
                    total_commits=total_commits
                )
                checkpoint_manager.save(checkpoint_data)
                
                LOGGER.info(f"✓ Summary generated for {commit_hash[:8]}")
                
            except Exception as e:
                LOGGER.error(f"✗ Failed to summarize {commit_hash[:8]}: {e}")
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


def compute_file_hash(file_path: Path) -> str:
    """Compute hash of a file or directory for checkpoint tracking.
    
    For directories (e.g. partitioned parquet datasets), hashes all files
    in sorted order to produce a deterministic result.
    
    Args:
        file_path: Path to file or directory
    
    Returns:
        First 16 characters of SHA256 hash
    """
    sha256 = hashlib.sha256()
    if file_path.is_dir():
        for child in sorted(file_path.rglob("*")):
            if child.is_file():
                with open(child, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        sha256.update(chunk)
    else:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
    return sha256.hexdigest()[:16]
