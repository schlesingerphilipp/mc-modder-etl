"""Configuration for the commit summarizer."""

import os
import hashlib
from dotenv import load_dotenv
from pathlib import Path
from app.utils.logging import LOGGER
# Load environment variables from .env
load_dotenv()


class SummarizerConfig:
    """Configuration for commit summarization."""
    
    def __init__(self, checkpoint_dir: Path = None):
        """Initialize configuration from environment variables."""
        self.lmstudio_model = os.getenv("LMSTUDIO_MODEL", "gpt-oss-20b")
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
        
        # Maximum diff length for truncation (in characters)
        self.max_diff_length = int(os.getenv("MAX_DIFF_LENGTH", "15000"))
        
        # Maximum diff length per file (in characters)
        self.max_file_diff_length = int(os.getenv("MAX_FILE_DIFF_LENGTH", "8000"))
        
        # File summary prompt template
        file_prompt_path = Path(__file__).parent / "FILE_SUMMARY_PROMPT.md"
        if not file_prompt_path.exists():
            raise FileNotFoundError(f"File summary prompt not found: {file_prompt_path}")
        with open(file_prompt_path, "r") as f:
            self.file_summary_prompt_template = f.read()
        
        # Commit synthesis prompt template
        synthesis_prompt_path = Path(__file__).parent / "COMMIT_SYNTHESIS_PROMPT.md"
        if not synthesis_prompt_path.exists():
            raise FileNotFoundError(f"Commit synthesis prompt not found: {synthesis_prompt_path}")
        with open(synthesis_prompt_path, "r") as f:
            self.commit_synthesis_prompt_template = f.read()
    
    def get_checkpoint_file(self, csv_hash: str, output_path: Path = None) -> Path:
        """Get the checkpoint file path for a specific CSV file and output target.
        
        Args:
            csv_hash: Hash of the CSV file to create unique checkpoints
            output_path: Optional output CSV path to differentiate checkpoints
        
        Returns:
            Path to the checkpoint file
        """
        LOGGER.info(f"Checkpoint directory: {self.checkpoint_dir}")
        
        if output_path:
            output_hash = hashlib.md5(str(output_path).encode()).hexdigest()[:8]
            return self.checkpoint_dir / f"checkpoint_{csv_hash}_{output_hash}.json"
        
        return self.checkpoint_dir / f"checkpoint_{csv_hash}.json"
