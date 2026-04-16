"""Configuration for ChromaDB connection."""

import os
from dotenv import load_dotenv
import chromadb

load_dotenv()


class ChromaConfig:
    """ChromaDB connection configuration from environment variables."""

    def __init__(self, collection_name: str = None):
        self.host = os.getenv("CHROMA_HOST", "chromadb")
        self.port = int(os.getenv("CHROMA_PORT", "8000"))
        self.collection_name = collection_name or os.getenv(
            "CHROMA_COLLECTION", "commit_summaries"
        )

    def get_client(self) -> chromadb.ClientAPI:
        """Create and return a ChromaDB HTTP client."""
        return chromadb.HttpClient(host=self.host, port=self.port)
