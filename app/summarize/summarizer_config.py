"""Configuration for the commit summarizer."""

import os
from dotenv import load_dotenv
from pathlib import Path
from app.utils.logging import LOGGER
# Load environment variables from .env
load_dotenv()


class SummarizerConfig:
    """Configuration for commit summarization."""
    
    def __init__(self, checkpoint_dir: Path = None):
        """Initialize configuration from environment variables."""
        self.lmstudio_model = os.getenv("LMSTUDIO_MODEL", "qwen3.5-9b")
        self.lmstudio_base_url = os.getenv("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1")
        self.lmstudio_api_key = os.getenv("LMSTUDIO_API_KEY", "not-needed")
        # Checkpoint configuration
        if checkpoint_dir is not None:
            LOGGER.info(f"Using checkpoint directory from argument: {checkpoint_dir}")
            self.checkpoint_dir = Path(checkpoint_dir)
        else:
            LOGGER.info("Using checkpoint directory from environment variable or default")
            checkpoint_dir = os.getenv("CHECKPOINT_DIR", "./checkpoints/summarize")
            self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # Semantic prompt template
        # read from app/summarize/PROMT.md
        prompt_path = Path(__file__).parent / "PROMPT.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
        with open(prompt_path, "r") as f:
            self.semantic_prompt_template = f.read()
        
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
        LOGGER.info(f"Checkpoint directory: {self.checkpoint_dir}")
        return self.checkpoint_dir / f"checkpoint_{csv_hash}.json"
