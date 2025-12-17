"""Gmail API client wrapper with categorization support."""

import base64
import logging
import re
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .auth import GmailAuth
from .config import CategoriesConfig, Category, Settings, get_categories_config, get_settings
from .models import (
    CategorySummary,
    DailySummary,
    Email,
    EmailAddress,
    EmailAttachment,
    EmailSummary,
    InboxStats,
    SearchQuery,
)

logger = logging.getLogger(__name__)


class GmailClient:
    """Gmail API client with email categorization."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        categories_config: Optional[CategoriesConfig] = None,
    ):
        self.settings = settings or get_settings()
        self.categories = categories_config or get_categories_config(self.settings)
        self.auth = GmailAuth(self.settings)
        self._service = None

    @property
    def service(self):
        """Get or create Gmail API service."""
        if self._service is None:
            credentials = self.auth.get_credentials()
            self._service = build("gmail", "v1", credentials=credentials)
        return self._service

    def _parse_email_address(self, raw: str) -> EmailAddress:
        """Parse email address from header value."""
        name, email = parseaddr(raw)
        return EmailAddress(email=email or raw, name=name or None)

    def _parse_email_addresses(self, raw: str) -> list[EmailAddress]:
        """Parse multiple email addresses from header."""
        if not raw:
            return []
        # Split by comma but respect quoted strings
        addresses = re.split(r",(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", raw)
        return [self._parse_email_address(addr.strip()) for addr in addresses if addr.strip()]

    def _get_header(self, headers: list[dict], name: str) -> str:
        """Get header value by name."""
        for header in headers:
            if header.get("name", "").lower() == name.lower():
                return header.get("value", "")
        return ""

    def _extract_body(self, payload: dict) -> tuple[Optional[str], Optional[str]]:
        """Extract plain text and HTML body from message payload."""
        text_body = None
        html_body = None

        def process_part(part: dict) -> None:
            nonlocal text_body, html_body
            mime_type = part.get("mimeType", "")

            if "parts" in part:
                for subpart in part["parts"]:
                    process_part(subpart)
            elif "body" in part and "data" in part["body"]:
                data = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                if mime_type == "text/plain" and not text_body:
                    text_body = data
                elif mime_type == "text/html" and not html_body:
                    html_body = data

        process_part(payload)
        return text_body, html_body

    def _extract_attachments(self, payload: dict) -> list[EmailAttachment]:
        """Extract attachment metadata from message payload."""
        attachments = []

        def process_part(part: dict) -> None:
            filename = part.get("filename", "")
            if filename and part.get("body", {}).get("attachmentId"):
                attachments.append(
                    EmailAttachment(
                        filename=filename,
                        mime_type=part.get("mimeType", "application/octet-stream"),
                        size=part.get("body", {}).get("size", 0),
                        attachment_id=part["body"]["attachmentId"],
                    )
                )
            if "parts" in part:
                for subpart in part["parts"]:
                    process_part(subpart)

        process_part(payload)
        return attachments

    def _categorize_email(self, email: Email) -> list[str]:
        """Determine which categories an email belongs to."""
        matched_categories = []
        sender_lower = email.sender.email.lower()
        sender_name_lower = (email.sender.name or "").lower()
        subject_lower = email.subject.lower()

        for cat_key, category in self.categories.categories.items():
            matcher = category.matcher

            # Check sender patterns
            for pattern in matcher.senders:
                if pattern in sender_lower or pattern in sender_name_lower:
                    matched_categories.append(cat_key)
                    break

            if cat_key in matched_categories:
                continue

            # Check subject patterns
            for pattern in matcher.subjects:
                if pattern in subject_lower:
                    matched_categories.append(cat_key)
                    break

            if cat_key in matched_categories:
                continue

            # Check labels
            email_labels_lower = [lbl.lower() for lbl in email.labels]
            for label in matcher.labels:
                if label.lower() in email_labels_lower:
                    matched_categories.append(cat_key)
                    break

        return matched_categories

    def _get_priority(self, categories: list[str]) -> str:
        """Get highest priority from matched categories."""
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        highest = "normal"
        highest_rank = priority_order["normal"]

        for cat_key in categories:
            if cat_key in self.categories.categories:
                cat_priority = self.categories.categories[cat_key].priority
                if priority_order.get(cat_priority, 2) < highest_rank:
                    highest = cat_priority
                    highest_rank = priority_order[cat_priority]

        return highest

    def _parse_message(self, msg: dict, include_body: bool = False) -> Email:
        """Parse Gmail API message into Email model."""
        payload = msg.get("payload", {})
        headers = payload.get("headers", [])

        # Parse date
        date_str = self._get_header(headers, "Date")
        try:
            date = parsedate_to_datetime(date_str)
        except Exception:
            # Fallback to internal date
            internal_date = int(msg.get("internalDate", 0)) / 1000
            date = datetime.fromtimestamp(internal_date, tz=timezone.utc)

        # Parse labels
        label_ids = msg.get("labelIds", [])
        is_read = "UNREAD" not in label_ids
        is_starred = "STARRED" in label_ids
        is_important = "IMPORTANT" in label_ids

        # Extract body if requested
        text_body, html_body = None, None
        if include_body:
            text_body, html_body = self._extract_body(payload)

        # Extract attachments
        attachments = self._extract_attachments(payload)

        email = Email(
            id=msg["id"],
            thread_id=msg["threadId"],
            subject=self._get_header(headers, "Subject") or "(No Subject)",
            snippet=msg.get("snippet", ""),
            body_text=text_body,
            body_html=html_body,
            sender=self._parse_email_address(self._get_header(headers, "From")),
            to=self._parse_email_addresses(self._get_header(headers, "To")),
            cc=self._parse_email_addresses(self._get_header(headers, "Cc")),
            reply_to=self._parse_email_address(self._get_header(headers, "Reply-To"))
            if self._get_header(headers, "Reply-To")
            else None,
            date=date,
            labels=label_ids,
            is_read=is_read,
            is_starred=is_starred,
            is_important=is_important,
            attachments=attachments,
            has_attachments=len(attachments) > 0,
        )

        # Categorize
        email.categories = self._categorize_email(email)
        email.priority = self._get_priority(email.categories)

        return email

    def _email_to_summary(self, email: Email) -> EmailSummary:
        """Convert Email to EmailSummary."""
        return EmailSummary(
            id=email.id,
            thread_id=email.thread_id,
            subject=email.subject,
            snippet=email.snippet,
            sender=email.sender,
            date=email.date,
            is_read=email.is_read,
            is_starred=email.is_starred,
            labels=email.labels,
            categories=email.categories,
            has_attachments=email.has_attachments,
        )

    def _build_query(self, search: SearchQuery) -> str:
        """Build Gmail search query from SearchQuery model."""
        parts = []

        if search.query:
            parts.append(search.query)
        if search.sender:
            parts.append(f"from:{search.sender}")
        if search.subject:
            parts.append(f"subject:{search.subject}")
        if search.is_unread is True:
            parts.append("is:unread")
        elif search.is_unread is False:
            parts.append("is:read")
        if search.has_attachment:
            parts.append("has:attachment")
        if search.after_date:
            parts.append(f"after:{search.after_date.strftime('%Y/%m/%d')}")
        if search.before_date:
            parts.append(f"before:{search.before_date.strftime('%Y/%m/%d')}")
        for label in search.labels:
            parts.append(f"label:{label}")

        return " ".join(parts) if parts else "in:inbox"

    async def get_email(self, message_id: str) -> Email:
        """Get a single email by ID with full content."""
        try:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return self._parse_message(msg, include_body=True)
        except HttpError as e:
            logger.error(f"Failed to get email {message_id}: {e}")
            raise

    async def list_emails(self, search: SearchQuery) -> list[EmailSummary]:
        """List emails matching search criteria."""
        query = self._build_query(search)
        logger.info(f"Searching emails with query: {query}")

        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=query, maxResults=search.max_results)
                .execute()
            )

            messages = results.get("messages", [])
            if not messages:
                return []

            # Fetch each message's metadata
            summaries = []
            for msg_ref in messages:
                msg = (
                    self.service.users()
                    .messages()
                    .get(userId="me", id=msg_ref["id"], format="metadata")
                    .execute()
                )
                email = self._parse_message(msg)

                # Filter by category if specified
                if search.category:
                    if search.category not in email.categories:
                        continue

                summaries.append(self._email_to_summary(email))

            return summaries
        except HttpError as e:
            logger.error(f"Failed to list emails: {e}")
            raise

    async def search_emails(self, query: str, max_results: int = 20) -> list[EmailSummary]:
        """Simple search interface for natural language queries."""
        search = SearchQuery(query=query, max_results=max_results)
        return await self.list_emails(search)

    async def get_unread_count(self) -> int:
        """Get count of unread emails in inbox."""
        try:
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:unread in:inbox", maxResults=1)
                .execute()
            )
            return results.get("resultSizeEstimate", 0)
        except HttpError as e:
            logger.error(f"Failed to get unread count: {e}")
            raise

    async def get_inbox_stats(self) -> InboxStats:
        """Get current inbox statistics."""
        try:
            # Get counts
            unread = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:unread in:inbox", maxResults=1)
                .execute()
            ).get("resultSizeEstimate", 0)

            starred = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:starred", maxResults=1)
                .execute()
            ).get("resultSizeEstimate", 0)

            important = (
                self.service.users()
                .messages()
                .list(userId="me", q="is:important is:unread", maxResults=1)
                .execute()
            ).get("resultSizeEstimate", 0)

            total = (
                self.service.users()
                .messages()
                .list(userId="me", q="in:inbox", maxResults=1)
                .execute()
            ).get("resultSizeEstimate", 0)

            return InboxStats(
                total_messages=total,
                unread_count=unread,
                starred_count=starred,
                important_count=important,
                updated_at=datetime.now(timezone.utc),
            )
        except HttpError as e:
            logger.error(f"Failed to get inbox stats: {e}")
            raise

    async def get_labels(self) -> list[dict]:
        """Get all Gmail labels."""
        try:
            results = self.service.users().labels().list(userId="me").execute()
            return results.get("labels", [])
        except HttpError as e:
            logger.error(f"Failed to get labels: {e}")
            raise

    async def create_label(self, name: str, background_color: str | None = None, text_color: str | None = None) -> dict:
        """Create a new Gmail label.
        
        Args:
            name: Label name (can include / for nested labels)
            background_color: Optional hex color for background (e.g., '#16a765')
            text_color: Optional hex color for text (e.g., '#ffffff')
            
        Returns:
            The created label object
        """
        try:
            label_body = {
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            }
            
            if background_color or text_color:
                label_body["color"] = {}
                if background_color:
                    label_body["color"]["backgroundColor"] = background_color
                if text_color:
                    label_body["color"]["textColor"] = text_color
            
            result = self.service.users().labels().create(
                userId="me",
                body=label_body
            ).execute()
            
            logger.info(f"Created label: {name} (ID: {result['id']})")
            return {"success": True, "label": result}
            
        except HttpError as e:
            logger.error(f"Failed to create label: {e}")
            return {"success": False, "error": str(e)}

    async def delete_label(self, label_id: str) -> dict:
        """Delete a Gmail label.
        
        Args:
            label_id: The ID of the label to delete
            
        Returns:
            Success/error dict
        """
        try:
            self.service.users().labels().delete(
                userId="me",
                id=label_id
            ).execute()
            
            logger.info(f"Deleted label: {label_id}")
            return {"success": True, "deleted_label_id": label_id}
            
        except HttpError as e:
            logger.error(f"Failed to delete label: {e}")
            return {"success": False, "error": str(e)}

    async def rename_label(self, label_id: str, new_name: str) -> dict:
        """Rename a Gmail label.
        
        Args:
            label_id: The ID of the label to rename
            new_name: The new name for the label
            
        Returns:
            Updated label object or error
        """
        try:
            result = self.service.users().labels().patch(
                userId="me",
                id=label_id,
                body={"name": new_name}
            ).execute()
            
            logger.info(f"Renamed label {label_id} to: {new_name}")
            return {"success": True, "label": result}
            
        except HttpError as e:
            logger.error(f"Failed to rename label: {e}")
            return {"success": False, "error": str(e)}

    async def modify_message_labels(
        self,
        message_ids: list[str],
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None
    ) -> dict:
        """Add or remove labels from messages.
        
        Args:
            message_ids: List of message IDs to modify
            add_label_ids: Label IDs to add to the messages
            remove_label_ids: Label IDs to remove from the messages
            
        Returns:
            Dict with success count and errors
        """
        if not message_ids:
            return {"success": 0, "errors": [], "message": "No message IDs provided"}
        
        if not add_label_ids and not remove_label_ids:
            return {"success": 0, "errors": [], "message": "No labels to add or remove"}
        
        results = {"success": 0, "errors": []}
        
        try:
            body = {"ids": message_ids}
            if add_label_ids:
                body["addLabelIds"] = add_label_ids
            if remove_label_ids:
                body["removeLabelIds"] = remove_label_ids
            
            # Use batchModify for efficiency
            if len(message_ids) <= 1000:
                self.service.users().messages().batchModify(
                    userId="me",
                    body=body
                ).execute()
                results["success"] = len(message_ids)
            else:
                # Process in batches of 1000
                for i in range(0, len(message_ids), 1000):
                    batch = message_ids[i:i+1000]
                    batch_body = body.copy()
                    batch_body["ids"] = batch
                    self.service.users().messages().batchModify(
                        userId="me",
                        body=batch_body
                    ).execute()
                    results["success"] += len(batch)
                    
        except HttpError as e:
            logger.error(f"Failed to modify message labels: {e}")
            results["errors"].append(str(e))
            
        return results

    async def find_label_by_name(self, name: str) -> dict | None:
        """Find a label by name (case-insensitive).
        
        Args:
            name: Label name to search for
            
        Returns:
            Label dict or None if not found
        """
        labels = await self.get_labels()
        name_lower = name.lower()
        for label in labels:
            if label.get("name", "").lower() == name_lower:
                return label
        return None

    async def get_daily_summary(
        self, lookback_hours: Optional[int] = None, include_read: bool = False
    ) -> DailySummary:
        """Generate a daily email summary organized by category."""
        if lookback_hours is None:
            lookback_hours = self.categories.summary_settings.get("daily_lookback_hours", 24)

        max_per_category = self.categories.summary_settings.get("max_per_category", 10)
        if include_read is None:
            include_read = self.categories.summary_settings.get("include_read", False)

        now = datetime.now(timezone.utc)
        period_start = now - timedelta(hours=lookback_hours)

        # Search for recent emails
        search = SearchQuery(
            after_date=period_start,
            is_unread=None if include_read else True,
            max_results=100,
        )

        all_emails = await self.list_emails(search)

        # Organize by category
        categorized: dict[str, list[EmailSummary]] = {
            cat_key: [] for cat_key in self.categories.categories.keys()
        }
        uncategorized: list[EmailSummary] = []

        for email in all_emails:
            if email.categories:
                for cat in email.categories:
                    if cat in categorized:
                        categorized[cat].append(email)
            else:
                uncategorized.append(email)

        # Build category summaries
        category_summaries = []
        for cat_key, category in self.categories.categories.items():
            emails = categorized.get(cat_key, [])[:max_per_category]
            if emails:
                category_summaries.append(
                    CategorySummary(
                        category_key=cat_key,
                        category_name=category.name,
                        priority=category.priority,
                        total_count=len(categorized.get(cat_key, [])),
                        unread_count=sum(1 for e in categorized.get(cat_key, []) if not e.is_read),
                        emails=emails,
                    )
                )

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
        category_summaries.sort(key=lambda c: priority_order.get(c.priority, 2))

        return DailySummary(
            generated_at=now,
            period_start=period_start,
            period_end=now,
            total_emails=len(all_emails),
            unread_emails=sum(1 for e in all_emails if not e.is_read),
            categories=category_summaries,
            uncategorized=uncategorized[:max_per_category],
        )

    async def get_category_summary(self, category_key: str) -> Optional[CategorySummary]:
        """Get summary for a specific category."""
        if category_key not in self.categories.categories:
            return None

        category = self.categories.categories[category_key]
        max_results = self.categories.summary_settings.get("max_per_category", 10)

        # Search for emails in this category
        search = SearchQuery(
            category=category_key,
            is_unread=True,
            max_results=50,
        )

        emails = await self.list_emails(search)

        return CategorySummary(
            category_key=category_key,
            category_name=category.name,
            priority=category.priority,
            total_count=len(emails),
            unread_count=sum(1 for e in emails if not e.is_read),
            emails=emails[:max_results],
        )

    async def mark_as_read(self, message_ids: list[str]) -> dict:
        """Mark one or more emails as read by removing the UNREAD label.
        
        Args:
            message_ids: List of Gmail message IDs to mark as read
            
        Returns:
            Dict with success count and any errors
        """
        if not message_ids:
            return {"success": 0, "errors": [], "message": "No message IDs provided"}
        
        results = {"success": 0, "errors": []}
        
        try:
            # Use batchModify for efficiency (up to 1000 at a time)
            if len(message_ids) <= 1000:
                self.service.users().messages().batchModify(
                    userId="me",
                    body={
                        "ids": message_ids,
                        "removeLabelIds": ["UNREAD"]
                    }
                ).execute()
                results["success"] = len(message_ids)
            else:
                # Process in batches of 1000
                for i in range(0, len(message_ids), 1000):
                    batch = message_ids[i:i+1000]
                    self.service.users().messages().batchModify(
                        userId="me",
                        body={
                            "ids": batch,
                            "removeLabelIds": ["UNREAD"]
                        }
                    ).execute()
                    results["success"] += len(batch)
                    
        except HttpError as e:
            logger.error(f"Failed to mark emails as read: {e}")
            results["errors"].append(str(e))
            
        return results

    async def mark_as_read_by_query(self, query: str, max_emails: int = 100) -> dict:
        """Mark emails matching a query as read.
        
        Args:
            query: Gmail search query (e.g., "from:newsletter@example.com", "older_than:7d")
            max_emails: Maximum number of emails to mark as read (safety limit)
            
        Returns:
            Dict with success count, matched count, and any errors
        """
        try:
            # First, find matching emails
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=f"{query} is:unread", maxResults=max_emails)
                .execute()
            )
            
            messages = results.get("messages", [])
            if not messages:
                return {
                    "matched": 0,
                    "success": 0,
                    "errors": [],
                    "message": "No unread emails matched the query"
                }
            
            message_ids = [msg["id"] for msg in messages]
            
            # Mark them as read
            mark_result = await self.mark_as_read(message_ids)
            mark_result["matched"] = len(messages)
            
            # Check if there might be more
            if len(messages) == max_emails:
                mark_result["message"] = f"Marked {mark_result['success']} emails as read. There may be more matching emails (limit was {max_emails})."
            else:
                mark_result["message"] = f"Marked {mark_result['success']} emails as read."
                
            return mark_result
            
        except HttpError as e:
            logger.error(f"Failed to search and mark emails: {e}")
            return {"matched": 0, "success": 0, "errors": [str(e)], "message": f"Error: {e}"}

    async def mark_as_unread(self, message_ids: list[str]) -> dict:
        """Mark one or more emails as unread by adding the UNREAD label.
        
        Args:
            message_ids: List of Gmail message IDs to mark as unread
            
        Returns:
            Dict with success count and any errors
        """
        if not message_ids:
            return {"success": 0, "errors": [], "message": "No message IDs provided"}
        
        results = {"success": 0, "errors": []}
        
        try:
            # Use batchModify for efficiency (up to 1000 at a time)
            if len(message_ids) <= 1000:
                self.service.users().messages().batchModify(
                    userId="me",
                    body={
                        "ids": message_ids,
                        "addLabelIds": ["UNREAD"]
                    }
                ).execute()
                results["success"] = len(message_ids)
            else:
                # Process in batches of 1000
                for i in range(0, len(message_ids), 1000):
                    batch = message_ids[i:i+1000]
                    self.service.users().messages().batchModify(
                        userId="me",
                        body={
                            "ids": batch,
                            "addLabelIds": ["UNREAD"]
                        }
                    ).execute()
                    results["success"] += len(batch)
                    
        except HttpError as e:
            logger.error(f"Failed to mark emails as unread: {e}")
            results["errors"].append(str(e))
            
        return results

    async def mark_as_unread_by_query(self, query: str, max_emails: int = 100) -> dict:
        """Mark emails matching a query as unread.
        
        Args:
            query: Gmail search query (e.g., "from:newsletter@example.com", "older_than:7d")
            max_emails: Maximum number of emails to mark as unread (safety limit)
            
        Returns:
            Dict with success count, matched count, and any errors
        """
        try:
            # First, find matching emails (that are currently read)
            results = (
                self.service.users()
                .messages()
                .list(userId="me", q=f"{query} -is:unread", maxResults=max_emails)
                .execute()
            )
            
            messages = results.get("messages", [])
            if not messages:
                return {
                    "matched": 0,
                    "success": 0,
                    "errors": [],
                    "message": "No read emails matched the query"
                }
            
            message_ids = [msg["id"] for msg in messages]
            
            # Mark them as unread
            mark_result = await self.mark_as_unread(message_ids)
            mark_result["matched"] = len(messages)
            
            # Check if there might be more
            if len(messages) == max_emails:
                mark_result["message"] = f"Marked {mark_result['success']} emails as unread. There may be more matching emails (limit was {max_emails})."
            else:
                mark_result["message"] = f"Marked {mark_result['success']} emails as unread."
                
            return mark_result
            
        except HttpError as e:
            logger.error(f"Failed to search and mark emails as unread: {e}")
            return {"matched": 0, "success": 0, "errors": [str(e)], "message": f"Error: {e}"}

    async def send_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        reply_to_message_id: str | None = None,
    ) -> dict:
        """Send an email.
        
        Args:
            to: List of recipient email addresses
            subject: Email subject
            body: Email body (plain text)
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to_message_id: Optional message ID to reply to (for threading)
            
        Returns:
            Dict with sent message info or error
        """
        try:
            # Create the email message
            message = MIMEText(body)
            message['to'] = ', '.join(to)
            message['subject'] = subject
            
            if cc:
                message['cc'] = ', '.join(cc)
            if bcc:
                message['bcc'] = ', '.join(bcc)
            
            # Handle reply threading
            thread_id = None
            if reply_to_message_id:
                # Get the original message to get thread ID and references
                try:
                    original = self.service.users().messages().get(
                        userId="me", 
                        id=reply_to_message_id,
                        format="metadata",
                        metadataHeaders=["Message-ID", "References", "In-Reply-To"]
                    ).execute()
                    
                    thread_id = original.get("threadId")
                    
                    # Get original Message-ID for threading headers
                    headers = original.get("payload", {}).get("headers", [])
                    original_message_id = None
                    references = None
                    
                    for header in headers:
                        if header["name"].lower() == "message-id":
                            original_message_id = header["value"]
                        elif header["name"].lower() == "references":
                            references = header["value"]
                    
                    # Set threading headers
                    if original_message_id:
                        message['In-Reply-To'] = original_message_id
                        if references:
                            message['References'] = f"{references} {original_message_id}"
                        else:
                            message['References'] = original_message_id
                            
                except HttpError as e:
                    logger.warning(f"Could not get original message for threading: {e}")
            
            # Encode the message
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            # Send the message
            body_data = {'raw': raw_message}
            if thread_id:
                body_data['threadId'] = thread_id
                
            sent_message = self.service.users().messages().send(
                userId="me",
                body=body_data
            ).execute()
            
            logger.info(f"Email sent successfully. Message ID: {sent_message['id']}")
            
            return {
                "success": True,
                "message_id": sent_message["id"],
                "thread_id": sent_message.get("threadId"),
                "to": to,
                "subject": subject,
            }
            
        except HttpError as e:
            logger.error(f"Failed to send email: {e}")
            return {
                "success": False,
                "error": str(e),
                "to": to,
                "subject": subject,
            }


