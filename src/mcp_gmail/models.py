"""Pydantic models for email data structures."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EmailAddress(BaseModel):
    """Email address with optional name."""

    email: str
    name: Optional[str] = None

    def __str__(self) -> str:
        if self.name:
            return f"{self.name} <{self.email}>"
        return self.email


class EmailAttachment(BaseModel):
    """Email attachment metadata."""

    filename: str
    mime_type: str
    size: int
    attachment_id: str


class Email(BaseModel):
    """Represents a Gmail message."""

    id: str = Field(..., description="Gmail message ID")
    thread_id: str = Field(..., description="Gmail thread ID")
    subject: str = Field(default="(No Subject)")
    snippet: str = Field(default="", description="Short preview of email content")
    body_text: Optional[str] = Field(default=None, description="Plain text body")
    body_html: Optional[str] = Field(default=None, description="HTML body")

    sender: EmailAddress
    to: list[EmailAddress] = Field(default_factory=list)
    cc: list[EmailAddress] = Field(default_factory=list)
    reply_to: Optional[EmailAddress] = None

    date: datetime
    labels: list[str] = Field(default_factory=list)
    is_read: bool = Field(default=False)
    is_starred: bool = Field(default=False)
    is_important: bool = Field(default=False)

    attachments: list[EmailAttachment] = Field(default_factory=list)
    has_attachments: bool = Field(default=False)

    # Categorization (added by our system)
    categories: list[str] = Field(default_factory=list)
    priority: str = Field(default="normal")


class EmailSummary(BaseModel):
    """Lightweight email summary for listings."""

    id: str
    thread_id: str
    subject: str
    snippet: str
    sender: EmailAddress
    date: datetime
    is_read: bool
    is_starred: bool
    labels: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    has_attachments: bool = Field(default=False)


class CategorySummary(BaseModel):
    """Summary of emails in a category."""

    category_key: str
    category_name: str
    priority: str
    total_count: int
    unread_count: int
    emails: list[EmailSummary] = Field(default_factory=list)


class DailySummary(BaseModel):
    """Daily email digest."""

    generated_at: datetime
    period_start: datetime
    period_end: datetime
    total_emails: int
    unread_emails: int
    categories: list[CategorySummary] = Field(default_factory=list)
    uncategorized: list[EmailSummary] = Field(default_factory=list)


class SearchQuery(BaseModel):
    """Search query parameters."""

    query: Optional[str] = Field(default=None, description="Gmail search query")
    sender: Optional[str] = Field(default=None, description="Filter by sender")
    subject: Optional[str] = Field(default=None, description="Filter by subject")
    labels: list[str] = Field(default_factory=list, description="Filter by labels")
    category: Optional[str] = Field(default=None, description="Filter by our category")
    is_unread: Optional[bool] = Field(default=None, description="Filter by read status")
    has_attachment: Optional[bool] = Field(default=None)
    after_date: Optional[datetime] = Field(default=None)
    before_date: Optional[datetime] = Field(default=None)
    max_results: int = Field(default=20, ge=1, le=100)


class InboxStats(BaseModel):
    """Current inbox statistics."""

    total_messages: int
    unread_count: int
    starred_count: int
    important_count: int
    categories: dict[str, int] = Field(
        default_factory=dict, description="Count per category"
    )
    updated_at: datetime
