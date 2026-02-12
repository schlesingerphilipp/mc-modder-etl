"""Configuration for the commit summarizer."""

import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env
load_dotenv()


class SummarizerConfig:
    """Configuration for commit summarization."""
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        # Google Gemini API configuration
        self.google_api_key = os.getenv("GOOGLE_API_KEY")
        if not self.google_api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")
        
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
        
        # Checkpoint configuration
        checkpoint_dir = os.getenv("CHECKPOINT_DIR", "./checkpoints")
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # Semantic prompt template
        self.semantic_prompt_template = os.getenv(
            "SEMANTIC_SUMMARY_PROMPT",
            """Analyze the following commit and provide a concise semantic summary (2-3 sentences) focusing on:
1. What problem or issue was solved
2. What code patterns or logic changed
3. The business or functional impact

Commit Message: {commit_message}

Unified Diff (all files changed):
{combined_diffs}

Provide only the semantic summary, no additional explanation."""
        )
        
        # Retry configuration
        self.max_retries = int(os.getenv("MAX_RETRIES", "3"))
        self.timeout_seconds = int(os.getenv("TIMEOUT_SECONDS", "60"))
    
    def get_checkpoint_file(self, csv_hash: str) -> Path:
        """Get the checkpoint file path for a specific CSV file.
        
        Args:
            csv_hash: Hash of the CSV file to create unique checkpoints
        
        Returns:
            Path to the checkpoint file
        """
        return self.checkpoint_dir / f"checkpoint_{csv_hash}.json"
