"""Pydantic models for the ETL pipeline."""

from typing import Optional
from pydantic import BaseModel, Field


class Commit(BaseModel):
    """Represents a git commit."""
    commit_hash: str = Field(..., description="Full commit SHA hash")
    message: str = Field(..., description="Commit message")
    diff: str = Field(default="", description="Unified diff output")


class PR(BaseModel):
    """Represents a GitHub Pull Request."""
    id: int = Field(..., description="GitHub PR ID")
    title: str = Field(..., description="PR title")
    body: Optional[str] = Field(default=None, description="PR description/body")
    user: str = Field(..., description="GitHub username who created PR")
    created_at: str = Field(..., description="ISO timestamp of PR creation")
    merged_at: Optional[str] = Field(default=None, description="ISO timestamp of merge (None if not merged)")


class ETLRow(BaseModel):
    """Represents a row in the final ETL output."""
    repo_id: str = Field(..., alias="Repo ID", description="Repository identifier (owner/repo)")
    commit_hash: str = Field(..., alias="commit hash", description="Full commit SHA hash")
    commit_message: str = Field(..., alias="commit message", description="Commit message")
    diff: str = Field(..., description="Unified diff output")
    pr_message: Optional[str] = Field(default=None, alias="PR message", description="PR description (null if no PR)")
    pr_id: Optional[int] = Field(default=None, alias="PR ID", description="GitHub PR ID (null if no PR)")
    
    model_config = {"populate_by_name": True}  # Allow both alias and field name


class CommitSummary(BaseModel):
    """Represents a commit with its semantic summary."""
    commit_hash: str = Field(..., description="Full commit SHA hash")
    original_message: str = Field(..., description="Original commit message")
    semantic_summary: Optional[str] = Field(default=None, description="LLM-generated semantic summary of changes")
    status: str = Field(default="pending", description="Processing status: pending, completed, or failed")
    error_message: Optional[str] = Field(default=None, description="Error message if status is failed")
