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
        self.embedding_base_url = os.getenv(
            "EMBEDDING_BASE_URL",
            os.getenv("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1"),
        )
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v1.5")
        self.embedding_api_key = os.getenv(
            "EMBEDDING_API_KEY",
            os.getenv("LMSTUDIO_API_KEY", "not-needed"),
        )

    def get_client(self) -> chromadb.ClientAPI:
        """Create and return a ChromaDB HTTP client."""
        return chromadb.HttpClient(host=self.host, port=self.port)
