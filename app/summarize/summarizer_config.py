"""Configuration for the commit summarizer."""

import os
from dotenv import load_dotenv
from pathlib import Path
from app.utils.logging import LOGGER
# Load environment variables from .env
load_dotenv()


class SummarizerConfig:
    """Configuration for commit summarization."""
    
    def __init__(self):
        """Initialize configuration from environment variables."""
        self.lmstudio_model = os.getenv("LMSTUDIO_MODEL", "gpt-oss-20b")
        self.lmstudio_base_url = os.getenv("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1")
        self.lmstudio_api_key = os.getenv("LMSTUDIO_API_KEY", "not-needed")
        
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
        
        # Maximum length of formatted file summaries before chunking (in characters)
        self.max_synthesis_length = int(os.getenv("MAX_SYNTHESIS_LENGTH", "8000"))
        
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
