"""Commit summarizer using LLM API with incremental parquet output."""

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote
from pydantic import BaseModel
import pandas as pd
from langchain_openai import ChatOpenAI

from app.summarize.summarizer_config import SummarizerConfig

from app.utils.logging import LOGGER


def _extract_json_value(content: str, key: str) -> str:
    """Extract a string value from a JSON response, handling truncated or malformed output.

    Tries in order:
    1. Standard json.loads
    2. Strip markdown code fences, then json.loads
    3. Repair truncated JSON (close open strings/braces)
    4. Regex extraction of the value

    Args:
        content: Raw LLM response text
        key: The JSON key to extract (e.g. "semantic_summary")

    Returns:
        The extracted string value

    Raises:
        ValueError: If the key cannot be extracted by any method
    """
    # 1. Try standard parse
    try:
        parsed = json.loads(content)
        return parsed[key]
    except (json.JSONDecodeError, KeyError):
        pass

    # 2. Strip markdown code fences and retry
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", content.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped).strip()
    if stripped != content.strip():
        try:
            parsed = json.loads(stripped)
            return parsed[key]
        except (json.JSONDecodeError, KeyError):
            pass
        content_to_repair = stripped
    else:
        content_to_repair = content.strip()

    # 3. Try to repair truncated JSON by closing open strings/braces
    repaired = content_to_repair.rstrip()
    if not repaired.endswith("}"):
        # Close an open string value if needed
        # Count unescaped quotes after the key's colon
        quote_count = 0
        in_escape = False
        for ch in repaired:
            if in_escape:
                in_escape = False
                continue
            if ch == "\\":
                in_escape = True
                continue
            if ch == '"':
                quote_count += 1
        if quote_count % 2 == 1:
            repaired += '"'
        if not repaired.endswith("}"):
            repaired += "}"
    try:
        parsed = json.loads(repaired)
        return parsed[key]
    except (json.JSONDecodeError, KeyError):
        pass

    # 4. Regex fallback: extract value after the key
    pattern = r'"' + re.escape(key) + r'"\s*:\s*"((?:[^"\\]|\\.)*)'
    m = re.search(pattern, content, re.DOTALL)
    if m:
        value = m.group(1)
        # Un-escape JSON string escapes
        value = value.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
        LOGGER.warning(
            f"Recovered truncated JSON for key '{key}' via regex ({len(value)} chars)"
        )
        return value

    raise ValueError(f"Could not extract key '{key}' from LLM response: {content[:200]}")

class CommitSummaryResult(BaseModel):
    """The summary of a commit diff"""
    semantic_summary: str


class FileSummaryResult(BaseModel):
    """The summary of a single file diff"""
    file_summary: str


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
            temperature=0,
            max_tokens=config.max_completion_tokens,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False}
            },
        )
        
        self.file_client = ChatOpenAI(
            model=config.lmstudio_model,
            base_url=config.lmstudio_base_url,
            api_key=config.lmstudio_api_key,
            temperature=0,
            max_tokens=config.max_completion_tokens,
            extra_body={
                "chat_template_kwargs": {"enable_thinking": False}
            },
        )
    
    def _prepare_prompt(self, prompt: str) -> str:
        """Prepare prompt for LLM, injecting /no_think if thinking is disabled.
        
        Qwen3 models require /no_think at the end of the user message
        to disable internal chain-of-thought reasoning.
        """
        if self.config.disable_thinking:
            return prompt + "\n/no_think"
        return prompt
    
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
        
        prompt = self._prepare_prompt(prompt)
        
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = self.file_client.invoke(prompt)
                LOGGER.debug(f"File LLM response: {response}")
                content = (response.content or "").strip()
                if not content:
                    raise ValueError(
                        f"LLM returned empty content for {file_path} "
                        f"(prompt length: {len(prompt)} chars)"
                    )
                return _extract_json_value(content, "file_summary")
            except Exception as e:
                last_error = e
                if attempt < self.config.max_retries - 1:
                    LOGGER.warning(f"File summary LLM call failed (attempt {attempt + 1}): {e}")
        
        LOGGER.error(f"File summary LLM call failed after {self.config.max_retries} attempts")
        raise Exception(f"File summary LLM call failed after {self.config.max_retries} attempts") from last_error
    
    def _file_checkpoint_path(self, output_dir: Path, repo_id: str, commit_hash: str) -> Path:
        """Get the path for a commit's file-summary checkpoint."""
        encoded_repo = quote(repo_id, safe="")
        checkpoint_dir = output_dir / f"Repo ID={encoded_repo}" / f"commit hash={commit_hash}"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return checkpoint_dir / "_file_summaries.json"

    def _load_file_checkpoint(self, checkpoint_path: Path) -> List[Dict[str, str]]:
        """Load previously checkpointed file summaries."""
        if not checkpoint_path.exists():
            return []
        try:
            with open(checkpoint_path, "r") as f:
                return json.load(f)
        except Exception as e:
            LOGGER.warning(f"Failed to load file checkpoint: {e}")
            return []

    def _save_file_checkpoint(self, checkpoint_path: Path, file_summaries: List[Dict[str, str]]) -> None:
        """Save file summaries checkpoint."""
        with open(checkpoint_path, "w") as f:
            json.dump(file_summaries, f, indent=2)

    def _delete_file_checkpoint(self, checkpoint_path: Path) -> None:
        """Remove the file-summary checkpoint after commit is fully written."""
        try:
            checkpoint_path.unlink(missing_ok=True)
        except Exception as e:
            LOGGER.warning(f"Failed to delete file checkpoint: {e}")

    def summarize_commit_files(
        self, group: pd.DataFrame,
        checkpoint_path: Path = None,
    ) -> List[Dict[str, str]]:
        """Summarize all files in a commit, with optional per-file checkpointing.
        
        Args:
            group: DataFrame group for a single commit
            checkpoint_path: Optional path to checkpoint file summaries
        
        Returns:
            List of dicts with file_path and summary
        """
        # Load any previously checkpointed file summaries
        file_summaries = self._load_file_checkpoint(checkpoint_path) if checkpoint_path else []
        done_files = {fs["file"] for fs in file_summaries}
        if done_files:
            LOGGER.info(f"Resuming file summaries: {len(done_files)} already done")
        
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
            
            if file_path in done_files:
                LOGGER.debug(f"Skipping already summarized file: {file_path}")
                continue
            
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
            
            # Checkpoint after each file
            if checkpoint_path:
                self._save_file_checkpoint(checkpoint_path, file_summaries)
        
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
        prompt = self._prepare_prompt(prompt)
        
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = self.commit_client.invoke(prompt)
                LOGGER.debug(f"Commit LLM response: {response}")
                content = (response.content or "").strip()
                if not content:
                    raise ValueError(
                        f"LLM returned empty content in response: {response}"
                        f"(prompt length: {len(prompt)} chars)"
                    )
                return _extract_json_value(content, "semantic_summary")
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
    
    def _commit_exists(self, output_dir: Path, repo_id: str, commit_hash: str) -> bool:
        """Check if a summary already exists for this repo+commit in the output parquet.
        
        Args:
            output_dir: Root output directory (partitioned parquet dataset)
            repo_id: Repository identifier
            commit_hash: Commit SHA hash
        
        Returns:
            True if a parquet partition already exists for this commit
        """
        # pyarrow URL-encodes partition values (e.g. / becomes %2F)
        encoded_repo = quote(repo_id, safe="")
        partition_path = output_dir / f"Repo ID={encoded_repo}" / f"commit hash={commit_hash}"
        return partition_path.exists() and any(partition_path.glob("*.parquet"))

    def _write_commit_summary(
        self, output_dir: Path, group: pd.DataFrame, summary: str
    ) -> None:
        """Write a single commit's summary to the partitioned parquet output.
        
        Args:
            output_dir: Root output directory
            group: DataFrame rows for this commit
            summary: Generated semantic summary
        """
        commit_row = group.iloc[0].copy()
        result = pd.DataFrame([{
            "Repo ID": commit_row.get("Repo ID", ""),
            "commit hash": commit_row["commit hash"],
            "commit message": commit_row["commit message"],
            "PR message": commit_row.get("PR message"),
            "PR ID": commit_row.get("PR ID"),
            "semantic_summary": summary,
        }])
        result.to_parquet(
            output_dir,
            engine="pyarrow",
            partition_cols=["Repo ID", "commit hash"],
            index=False,
        )

    def process_commits(
        self,
        df: pd.DataFrame,
        output_dir: Path,
    ) -> Dict[str, int]:
        """Process commits and write summaries incrementally to parquet.
        
        For each commit, checks if a parquet partition already exists.
        If not, generates the summary and writes it immediately.
        
        Args:
            df: DataFrame from ETL parquet input
            output_dir: Output directory for partitioned parquet (Repo ID / commit hash)
        
        Returns:
            Dict with counts: processed, skipped, failed
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        commit_groups = self.group_rows_by_commit(df)
        total_commits = len(commit_groups)
        processed = 0
        skipped = 0
        failed = 0
        
        for i, (commit_hash, group) in enumerate(commit_groups.items(), 1):
            repo_id = str(group.iloc[0].get("Repo ID", ""))
            LOGGER.info(f"Processing commit {i}/{total_commits}: {commit_hash[:8]} in repo {repo_id}")
            if self._commit_exists(output_dir, repo_id, commit_hash):
                LOGGER.debug(f"Skipping already processed commit: {commit_hash[:8]}")
                skipped += 1
                continue
            
            try:
                LOGGER.info(f"Processing commit {i}/{total_commits}: {commit_hash[:8]}...")
                
                commit_message = group.iloc[0]["commit message"]
                
                # File-level checkpointing
                checkpoint_path = os.environ.get("CHECKPOINT_DIR", os.getcwd() + "./checkpoints") 
                cp_path = self._file_checkpoint_path(output_dir, repo_id, commit_hash)
                file_summaries = self.summarize_commit_files(group, checkpoint_path=cp_path)
                
                summary = self.synthesize_commit_summary(commit_message, file_summaries)
                LOGGER.debug(f"Generated summary: {summary[:200]}")
                
                self._write_commit_summary(output_dir, group, summary)
                self._delete_file_checkpoint(cp_path)
                processed += 1
                
                LOGGER.info(f"✓ Summary generated for {commit_hash[:8]}")
                
            except Exception as e:
                LOGGER.error(f"✗ Failed to summarize {commit_hash[:8]}: {e}")
                failed += 1
        
        return {"processed": processed, "skipped": skipped, "failed": failed}
