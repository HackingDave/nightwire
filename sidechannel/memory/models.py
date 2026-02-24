"""Pydantic models for the memory system."""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field


class User(BaseModel):
    """User profile for memory partitioning."""

    phone_number: str = Field(..., description="E.164 format phone number")
    display_name: Optional[str] = None
    first_seen: datetime = Field(default_factory=datetime.now)
    last_active: datetime = Field(default_factory=datetime.now)
    total_messages: int = 0


class Session(BaseModel):
    """Conversation session grouping."""

    id: str = Field(..., description="Unique session identifier")
    phone_number: str
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    project_name: Optional[str] = None
    summary: Optional[str] = None
    message_count: int = 0


class Conversation(BaseModel):
    """A single conversation message."""

    id: Optional[int] = None
    phone_number: str
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    role: str = Field(..., description="'user' or 'assistant'")
    content: str
    project_name: Optional[str] = None
    command_type: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    embedding_id: Optional[int] = None


class Preference(BaseModel):
    """User preference or learned fact."""

    id: Optional[int] = None
    phone_number: str
    category: str = Field(..., description="'style', 'project', 'personal', 'technical'")
    key: str
    value: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_conversation_id: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)
    last_used: Optional[datetime] = None
    use_count: int = 0


class ExplicitMemory(BaseModel):
    """Explicitly stored memory via /remember command."""

    id: Optional[int] = None
    phone_number: str
    memory_text: str
    tags: Optional[List[str]] = None
    project_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    embedding_id: Optional[int] = None


class SearchResult(BaseModel):
    """Result from semantic search."""

    id: int
    content: str
    role: str
    timestamp: datetime
    project_name: Optional[str] = None
    similarity_score: float = Field(..., ge=-1.0, le=1.0)
    source_type: str = Field(default="conversation", description="'conversation' or 'memory'")


class MemoryContext(BaseModel):
    """Assembled context for prompt injection."""

    preferences: List[Preference] = Field(default_factory=list)
    explicit_memories: List[ExplicitMemory] = Field(default_factory=list)
    relevant_history: List[SearchResult] = Field(default_factory=list)
    summarized_context: Optional[str] = None
    token_count: int = 0
