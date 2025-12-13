"""Tests for email models."""

from datetime import datetime, timezone

import pytest

from mcp_gmail.models import (
    CategorySummary,
    DailySummary,
    Email,
    EmailAddress,
    EmailAttachment,
    EmailSummary,
    InboxStats,
    SearchQuery,
)


class TestEmailAddress:
    """Tests for EmailAddress model."""

    def test_email_only(self):
        """Test email address without name."""
        addr = EmailAddress(email="test@example.com")
        assert str(addr) == "test@example.com"

    def test_email_with_name(self):
        """Test email address with display name."""
        addr = EmailAddress(email="test@example.com", name="Test User")
        assert str(addr) == "Test User <test@example.com>"


class TestEmail:
    """Tests for Email model."""

    def test_minimal_email(self):
        """Test email with minimal required fields."""
        email = Email(
            id="123",
            thread_id="456",
            sender=EmailAddress(email="sender@test.com"),
            date=datetime.now(timezone.utc),
        )
        assert email.id == "123"
        assert email.subject == "(No Subject)"
        assert email.is_read is False
        assert email.categories == []

    def test_full_email(self):
        """Test email with all fields."""
        email = Email(
            id="123",
            thread_id="456",
            subject="Test Subject",
            snippet="This is a test...",
            body_text="Full body text",
            sender=EmailAddress(email="sender@test.com", name="Sender"),
            to=[EmailAddress(email="recipient@test.com")],
            date=datetime.now(timezone.utc),
            labels=["INBOX", "IMPORTANT"],
            is_read=True,
            is_starred=True,
            is_important=True,
            categories=["work", "action_required"],
            priority="high",
        )
        assert email.subject == "Test Subject"
        assert email.is_read is True
        assert "work" in email.categories


class TestSearchQuery:
    """Tests for SearchQuery model."""

    def test_default_query(self):
        """Test default search query."""
        query = SearchQuery()
        assert query.max_results == 20
        assert query.is_unread is None

    def test_custom_query(self):
        """Test custom search parameters."""
        query = SearchQuery(
            query="from:test@example.com",
            is_unread=True,
            max_results=50,
            labels=["Work"],
        )
        assert query.query == "from:test@example.com"
        assert query.is_unread is True
        assert query.max_results == 50


class TestDailySummary:
    """Tests for DailySummary model."""

    def test_empty_summary(self):
        """Test empty daily summary."""
        summary = DailySummary(
            generated_at=datetime.now(timezone.utc),
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc),
            total_emails=0,
            unread_emails=0,
        )
        assert summary.categories == []
        assert summary.uncategorized == []

    def test_summary_with_categories(self):
        """Test summary with categorized emails."""
        email = EmailSummary(
            id="1",
            thread_id="1",
            subject="Test",
            snippet="...",
            sender=EmailAddress(email="test@test.com"),
            date=datetime.now(timezone.utc),
            is_read=False,
            is_starred=False,
            categories=["navy"],
        )
        
        cat_summary = CategorySummary(
            category_key="navy",
            category_name="Navy",
            priority="high",
            total_count=1,
            unread_count=1,
            emails=[email],
        )
        
        summary = DailySummary(
            generated_at=datetime.now(timezone.utc),
            period_start=datetime.now(timezone.utc),
            period_end=datetime.now(timezone.utc),
            total_emails=1,
            unread_emails=1,
            categories=[cat_summary],
        )
        
        assert len(summary.categories) == 1
        assert summary.categories[0].category_key == "navy"
