"""MCP Server implementation for Gmail.

Refactored for Google Gemini compatibility with strict type hints and docstrings.
"""

import asyncio
import logging
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Resource, TextContent

from .config import get_categories_config, get_settings
from .gmail_client import GmailClient
from .models import SearchQuery

logger = logging.getLogger(__name__)

# Initialize server
server = Server("gmail-mcp")

# Global client instance
_gmail_client: GmailClient | None = None


def get_gmail_client() -> GmailClient:
    """Get or create Gmail client instance."""
    global _gmail_client
    if _gmail_client is None:
        settings = get_settings()
        categories = get_categories_config(settings)
        _gmail_client = GmailClient(settings, categories)
    return _gmail_client


# ============================================================================
# TOOLS - Refactored for Google Gemini compatibility
# ============================================================================


@server.tool()
async def gmail_search(query: str, max_results: int = 20) -> str:
    """
    Search emails using Gmail query syntax or natural language.

    Args:
        query: Gmail search query string. Examples: 'from:john@example.com',
               'subject:meeting', 'is:unread', 'has:attachment', 'newer_than:7d'.
        max_results: Maximum number of email results to return. Defaults to 20, maximum 100.

    Returns:
        Formatted list of matching emails with subject, sender, date, and snippet.
    """
    client = get_gmail_client()
    max_results = min(max_results, 100)
    results = await client.search_emails(query, max_results)
    return _format_email_list(results)


@server.tool()
async def gmail_list_unread(category: str = "", max_results: int = 20) -> str:
    """
    List unread emails, optionally filtered by category.

    Args:
        category: Optional category filter. Valid values: 'navy', 'kids', 'financial',
                  'action_required'. Leave empty for all unread emails.
        max_results: Maximum number of results to return. Defaults to 20.

    Returns:
        Formatted list of unread emails with subject, sender, date, and snippet.
    """
    client = get_gmail_client()
    search = SearchQuery(
        is_unread=True,
        category=category if category else None,
        max_results=max_results,
    )
    results = await client.list_emails(search)
    return _format_email_list(results)


@server.tool()
async def gmail_get_email(email_id: str) -> str:
    """
    Get the full content of a specific email by its ID.

    Args:
        email_id: The Gmail message ID. You can get this from search results or list operations.

    Returns:
        Full email content including subject, sender, recipients, date, labels, and body text.
    """
    client = get_gmail_client()
    if not email_id:
        return "Error: email_id is required"
    email = await client.get_email(email_id)
    return _format_full_email(email)


@server.tool()
async def gmail_daily_summary(hours: int = 24, include_read: bool = False) -> str:
    """
    Generate a daily summary of emails organized by category.

    Categories include Navy, Kids, Financial, and Action Items.

    Args:
        hours: How many hours back to look for emails. Defaults to 24.
        include_read: Whether to include already read emails. Defaults to False (unread only).

    Returns:
        Formatted summary with email counts and details organized by category.
    """
    client = get_gmail_client()
    summary = await client.get_daily_summary(hours, include_read)
    return _format_daily_summary(summary)


@server.tool()
async def gmail_category_summary(category: str) -> str:
    """
    Get a summary of unread emails in a specific category.

    Args:
        category: Category to summarize. Valid values: 'navy', 'kids', 'financial', 'action_required'.

    Returns:
        Summary of unread emails in that category with subject, sender, date, and preview.
    """
    client = get_gmail_client()
    if not category:
        return "Error: category is required"
    summary = await client.get_category_summary(category)
    if summary is None:
        return f"Unknown category: {category}. Valid categories: navy, kids, financial, action_required"
    return _format_category_summary(summary)


@server.tool()
async def gmail_inbox_stats() -> str:
    """
    Get current inbox statistics including unread count, starred, and important emails.

    Returns:
        Inbox statistics with total messages, unread count, starred count, and important count.
    """
    client = get_gmail_client()
    stats = await client.get_inbox_stats()
    return _format_inbox_stats(stats)


@server.tool()
async def gmail_get_labels() -> str:
    """
    List all Gmail labels and folders.

    Returns:
        List of all user labels and system labels in the Gmail account.
    """
    client = get_gmail_client()
    labels = await client.get_labels()
    return _format_labels(labels)


@server.tool()
async def gmail_get_categories() -> str:
    """
    List configured email categories and their matching rules.

    Returns:
        Configuration details for each category including name, priority, and matching patterns.
    """
    categories = get_categories_config()
    return _format_categories_config(categories)


@server.tool()
async def gmail_mark_as_read_by_ids(
    message_ids: str,
    confirm: bool = False
) -> str:
    """
    Mark specific emails as read by their message IDs.

    Args:
        message_ids: Comma-separated list of Gmail message IDs to mark as read.
                     Example: 'abc123,def456,ghi789'.
        confirm: Must be True to actually mark emails as read. Set to False to preview
                 what would be marked. Defaults to False.

    Returns:
        Preview of emails to be marked, or confirmation of how many were marked as read.
    """
    client = get_gmail_client()
    
    # Parse comma-separated IDs
    ids_list = [id.strip() for id in message_ids.split(",") if id.strip()]
    
    if not ids_list:
        return "Error: message_ids is required. Provide comma-separated Gmail message IDs."
    
    if not confirm:
        return f"⚠️ Preview: {len(ids_list)} email(s) would be marked as read.\n\nTo proceed, call this tool again with confirm=True"
    
    result = await client.mark_as_read(ids_list)
    return (
        f"✅ Marked {result['success']} email(s) as read."
        + (f"\nErrors: {result['errors']}" if result['errors'] else "")
    )


@server.tool()
async def gmail_mark_as_read_by_query(
    query: str,
    max_emails: int = 100,
    confirm: bool = False
) -> str:
    """
    Mark emails matching a search query as read.

    Args:
        query: Gmail search query to find emails. Examples: 'from:newsletter@example.com',
               'older_than:7d', 'subject:promotion', 'label:updates'.
        max_emails: Maximum number of emails to mark as read. Safety limit, defaults to 100,
                    maximum 500.
        confirm: Must be True to actually mark emails as read. Set to False to preview
                 what would be marked. Defaults to False.

    Returns:
        Preview of matching emails to be marked, or confirmation of how many were marked.
    """
    client = get_gmail_client()
    
    if not query:
        return "Error: query is required. Provide a Gmail search query."
    
    max_emails = min(max_emails, 500)  # Cap at 500 for safety
    
    if not confirm:
        # Preview mode - show what would be marked
        search_results = await client.search_emails(f"{query} is:unread", max_emails)
        if not search_results:
            return f"No unread emails match the query: {query}"
        
        lines = [
            f"⚠️ Preview: The following {len(search_results)} email(s) would be marked as read:\n",
        ]
        for email in search_results[:20]:  # Show first 20
            lines.append(f"• {email.subject}")
            lines.append(f"  From: {email.sender.email}")
            lines.append(f"  Date: {email.date.strftime('%Y-%m-%d %H:%M')}")
            lines.append("")
        
        if len(search_results) > 20:
            lines.append(f"... and {len(search_results) - 20} more\n")
        
        lines.append("To proceed, call this tool again with confirm=True")
        
        return "\n".join(lines)
    
    # Actually mark as read
    result = await client.mark_as_read_by_query(query, max_emails)
    return (
        f"✅ {result['message']}\n\nMatched: {result['matched']}\nMarked as read: {result['success']}"
        + (f"\nErrors: {result['errors']}" if result['errors'] else "")
    )


@server.tool()
async def gmail_send_email(
    to_recipients: str,
    subject: str,
    body: str,
    cc_recipients: str = "",
    bcc_recipients: str = "",
    reply_to_message_id: str = "",
    confirm: bool = False
) -> str:
    """
    Send an email. Can send new emails or reply to existing threads.

    Args:
        to_recipients: Comma-separated list of recipient email addresses.
                       Example: 'john@example.com,jane@example.com'.
        subject: Email subject line.
        body: Email body text in plain text format.
        cc_recipients: Optional comma-separated list of CC recipient email addresses.
        bcc_recipients: Optional comma-separated list of BCC recipient email addresses.
        reply_to_message_id: Optional Gmail message ID to reply to for threading.
        confirm: Must be True to actually send the email. Set to False to preview.
                 Defaults to False.

    Returns:
        Preview of the email to be sent, or confirmation with sent message details.
    """
    client = get_gmail_client()
    
    # Parse comma-separated recipients
    to_list = [r.strip() for r in to_recipients.split(",") if r.strip()]
    cc_list = [r.strip() for r in cc_recipients.split(",") if r.strip()] if cc_recipients else []
    bcc_list = [r.strip() for r in bcc_recipients.split(",") if r.strip()] if bcc_recipients else []
    
    # Validate required fields
    if not to_list:
        return "Error: to_recipients is required. Provide comma-separated email addresses."
    if not subject:
        return "Error: subject is required."
    if not body:
        return "Error: body is required."
    
    if not confirm:
        # Preview mode
        lines = [
            "⚠️ Preview: The following email would be sent:\n",
            f"To: {', '.join(to_list)}",
        ]
        if cc_list:
            lines.append(f"CC: {', '.join(cc_list)}")
        if bcc_list:
            lines.append(f"BCC: {', '.join(bcc_list)}")
        lines.append(f"Subject: {subject}")
        if reply_to_message_id:
            lines.append(f"Reply to message: {reply_to_message_id}")
        lines.append(f"\n--- Body ---\n{body[:500]}")
        if len(body) > 500:
            lines.append(f"\n... ({len(body) - 500} more characters)")
        lines.append("\n\nTo send this email, call this tool again with confirm=True")
        
        return "\n".join(lines)
    
    # Actually send the email
    result = await client.send_email(
        to=to_list,
        subject=subject,
        body=body,
        cc=cc_list if cc_list else None,
        bcc=bcc_list if bcc_list else None,
        reply_to_message_id=reply_to_message_id if reply_to_message_id else None,
    )
    
    if result["success"]:
        return (
            f"✅ Email sent successfully!\n\n"
            f"To: {', '.join(result['to'])}\n"
            f"Subject: {result['subject']}\n"
            f"Message ID: {result['message_id']}"
        )
    else:
        return f"❌ Failed to send email.\n\nError: {result['error']}"


@server.tool()
async def gmail_list_labels() -> str:
    """
    List all Gmail labels with their IDs, separated by system and user labels.

    Returns:
        Complete list of Gmail labels with their IDs and colors (for user labels).
    """
    client = get_gmail_client()
    labels = await client.get_labels()
    lines = ["📁 Gmail Labels:\n"]
    
    # Separate system and user labels
    system_labels = []
    user_labels = []
    for label in labels:
        if label.get("type") == "system":
            system_labels.append(label)
        else:
            user_labels.append(label)
    
    if system_labels:
        lines.append("**System Labels:**")
        for label in sorted(system_labels, key=lambda x: x.get("name", "")):
            lines.append(f"  • {label['name']} (ID: {label['id']})")
    
    if user_labels:
        lines.append("\n**User Labels:**")
        for label in sorted(user_labels, key=lambda x: x.get("name", "")):
            color_info = ""
            if label.get("color"):
                color_info = f" [color: {label['color'].get('backgroundColor', 'default')}]"
            lines.append(f"  • {label['name']} (ID: {label['id']}){color_info}")
    
    return "\n".join(lines)


@server.tool()
async def gmail_create_label(
    label_name: str,
    background_color: str = "",
    text_color: str = ""
) -> str:
    """
    Create a new Gmail label.

    Args:
        label_name: Name for the new label. Use '/' for nested labels (e.g., 'Work/Projects').
        background_color: Optional hex color for label background (e.g., '#16a765').
        text_color: Optional hex color for label text (e.g., '#ffffff').

    Returns:
        Confirmation with the created label name and ID, or error message.
    """
    client = get_gmail_client()
    
    if not label_name:
        return "Error: label_name is required."
    
    # Check if label already exists
    existing = await client.find_label_by_name(label_name)
    if existing:
        return f"❌ A label named '{label_name}' already exists (ID: {existing['id']})"
    
    result = await client.create_label(
        label_name,
        background_color if background_color else None,
        text_color if text_color else None
    )
    
    if result["success"]:
        label = result["label"]
        return f"✅ Created label: {label['name']}\nID: {label['id']}"
    else:
        return f"❌ Failed to create label: {result['error']}"


@server.tool()
async def gmail_delete_label(
    label_name: str = "",
    label_id: str = "",
    confirm: bool = False
) -> str:
    """
    Delete a Gmail label.

    Args:
        label_name: Name of the label to delete. Either label_name or label_id must be provided.
        label_id: ID of the label to delete. Either label_name or label_id must be provided.
        confirm: Must be True to actually delete the label. Defaults to False for preview.

    Returns:
        Preview of label to be deleted, or confirmation of deletion.
    """
    client = get_gmail_client()
    
    if not label_id and not label_name:
        return "Error: Either label_name or label_id is required."
    
    # Find label by name if ID not provided
    if not label_id:
        label = await client.find_label_by_name(label_name)
        if not label:
            return f"❌ Label not found: {label_name}"
        label_id = label["id"]
        found_name = label["name"]
    else:
        found_name = label_name if label_name else label_id
    
    if not confirm:
        return f"⚠️ Preview: Label '{found_name}' (ID: {label_id}) would be deleted.\n\nTo proceed, call this tool again with confirm=True"
    
    result = await client.delete_label(label_id)
    if result["success"]:
        return f"✅ Deleted label: {found_name}"
    else:
        return f"❌ Failed to delete label: {result['error']}"


@server.tool()
async def gmail_rename_label(
    new_name: str,
    label_name: str = "",
    label_id: str = ""
) -> str:
    """
    Rename an existing Gmail label.

    Args:
        new_name: The new name for the label.
        label_name: Current name of the label. Either label_name or label_id must be provided.
        label_id: ID of the label to rename. Either label_name or label_id must be provided.

    Returns:
        Confirmation with old and new label names, or error message.
    """
    client = get_gmail_client()
    
    if not label_id and not label_name:
        return "Error: Either label_name or label_id is required."
    if not new_name:
        return "Error: new_name is required."
    
    # Find label by name if ID not provided
    if not label_id:
        label = await client.find_label_by_name(label_name)
        if not label:
            return f"❌ Label not found: {label_name}"
        label_id = label["id"]
        old_name = label["name"]
    else:
        old_name = label_name if label_name else label_id
    
    result = await client.rename_label(label_id, new_name)
    if result["success"]:
        return f"✅ Renamed label: {old_name} → {new_name}"
    else:
        return f"❌ Failed to rename label: {result['error']}"


@server.tool()
async def gmail_add_label_to_messages(
    label_name: str,
    message_ids: str = "",
    query: str = "",
    max_messages: int = 100,
    confirm: bool = False
) -> str:
    """
    Add a label to one or more emails.

    Args:
        label_name: Name of the label to add to messages.
        message_ids: Comma-separated Gmail message IDs. Either message_ids or query must be provided.
        query: Gmail search query to find messages. Either message_ids or query must be provided.
        max_messages: Maximum messages to modify when using query. Defaults to 100, max 500.
        confirm: Must be True to actually add the label. Defaults to False for preview.

    Returns:
        Preview of messages to be modified, or confirmation of how many were modified.
    """
    client = get_gmail_client()
    
    if not label_name:
        return "Error: label_name is required."
    
    # Parse message IDs if provided
    ids_list = [id.strip() for id in message_ids.split(",") if id.strip()] if message_ids else []
    
    if not ids_list and not query:
        return "Error: Either message_ids or query is required."
    
    # Find label
    label = await client.find_label_by_name(label_name)
    if not label:
        return f"❌ Label not found: {label_name}"
    label_id = label["id"]
    
    # Get message IDs from query if provided
    if query and not ids_list:
        max_messages = min(max_messages, 500)
        search_results = await client.search_emails(query, max_messages)
        if not search_results:
            return f"No emails found matching query: {query}"
        ids_list = [email.id for email in search_results]
    
    if not confirm:
        return f"⚠️ Preview: Would add label '{label_name}' to {len(ids_list)} message(s).\n\nTo proceed, call this tool again with confirm=True"
    
    result = await client.modify_message_labels(ids_list, add_label_ids=[label_id])
    
    if result["success"] > 0:
        return (
            f"✅ Added label '{label_name}' to {result['success']} message(s)."
            + (f"\nErrors: {result['errors']}" if result['errors'] else "")
        )
    else:
        return f"❌ Failed to add label: {result['errors']}"


@server.tool()
async def gmail_remove_label_from_messages(
    label_name: str,
    message_ids: str = "",
    query: str = "",
    max_messages: int = 100,
    confirm: bool = False
) -> str:
    """
    Remove a label from one or more emails.

    Args:
        label_name: Name of the label to remove from messages.
        message_ids: Comma-separated Gmail message IDs. Either message_ids or query must be provided.
        query: Gmail search query to find messages. Either message_ids or query must be provided.
        max_messages: Maximum messages to modify when using query. Defaults to 100, max 500.
        confirm: Must be True to actually remove the label. Defaults to False for preview.

    Returns:
        Preview of messages to be modified, or confirmation of how many were modified.
    """
    client = get_gmail_client()
    
    if not label_name:
        return "Error: label_name is required."
    
    # Parse message IDs if provided
    ids_list = [id.strip() for id in message_ids.split(",") if id.strip()] if message_ids else []
    
    if not ids_list and not query:
        return "Error: Either message_ids or query is required."
    
    # Find label
    label = await client.find_label_by_name(label_name)
    if not label:
        return f"❌ Label not found: {label_name}"
    label_id = label["id"]
    
    # Get message IDs from query if provided
    if query and not ids_list:
        max_messages = min(max_messages, 500)
        search_results = await client.search_emails(query, max_messages)
        if not search_results:
            return f"No emails found matching query: {query}"
        ids_list = [email.id for email in search_results]
    
    if not confirm:
        return f"⚠️ Preview: Would remove label '{label_name}' from {len(ids_list)} message(s).\n\nTo proceed, call this tool again with confirm=True"
    
    result = await client.modify_message_labels(ids_list, remove_label_ids=[label_id])
    
    if result["success"] > 0:
        return (
            f"✅ Removed label '{label_name}' from {result['success']} message(s)."
            + (f"\nErrors: {result['errors']}" if result['errors'] else "")
        )
    else:
        return f"❌ Failed to remove label: {result['errors']}"


# ============================================================================
# RESOURCES
# ============================================================================


@server.list_resources()
async def list_resources() -> list[Resource]:
    """List available Gmail resources."""
    return [
        Resource(
            uri="gmail://inbox/stats",
            name="Inbox Statistics",
            description="Current inbox statistics including unread count",
            mimeType="application/json",
        ),
        Resource(
            uri="gmail://summary/daily",
            name="Daily Summary",
            description="Daily email summary organized by category",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    """Read a Gmail resource."""
    client = get_gmail_client()

    if uri == "gmail://inbox/stats":
        stats = await client.get_inbox_stats()
        return stats.model_dump_json(indent=2)

    elif uri == "gmail://summary/daily":
        summary = await client.get_daily_summary()
        return summary.model_dump_json(indent=2)

    else:
        raise ValueError(f"Unknown resource: {uri}")


# ============================================================================
# FORMATTING HELPERS
# ============================================================================


def _format_email_list(emails: list) -> str:
    """Format email list for display."""
    if not emails:
        return "No emails found."

    lines = [f"Found {len(emails)} email(s):\n"]
    for email in emails:
        status = "📬" if not email.is_read else "📭"
        star = "⭐" if email.is_starred else ""
        attachment = "📎" if email.has_attachments else ""
        categories = f" [{', '.join(email.categories)}]" if email.categories else ""

        lines.append(
            f"{status}{star}{attachment} **{email.subject}**{categories}\n"
            f"   From: {email.sender}\n"
            f"   Date: {email.date.strftime('%Y-%m-%d %H:%M')}\n"
            f"   ID: `{email.id}`\n"
            f"   {email.snippet[:100]}...\n"
        )
    return "\n".join(lines)


def _format_full_email(email) -> str:
    """Format full email for display."""
    categories = f"Categories: {', '.join(email.categories)}" if email.categories else ""

    attachments = ""
    if email.attachments:
        att_list = ", ".join(a.filename for a in email.attachments)
        attachments = f"\nAttachments: {att_list}"

    body = email.body_text or "(No text content)"
    if len(body) > 2000:
        body = body[:2000] + "\n\n... [truncated]"

    return f"""
**Subject:** {email.subject}
**From:** {email.sender}
**To:** {', '.join(str(t) for t in email.to)}
**Date:** {email.date.strftime('%Y-%m-%d %H:%M:%S')}
**Labels:** {', '.join(email.labels)}
{categories}
{attachments}

---

{body}
"""


def _format_daily_summary(summary) -> str:
    """Format daily summary for display."""
    lines = [
        f"# 📧 Daily Email Summary",
        f"**Period:** {summary.period_start.strftime('%Y-%m-%d %H:%M')} to {summary.period_end.strftime('%Y-%m-%d %H:%M')}",
        f"**Total Emails:** {summary.total_emails} ({summary.unread_emails} unread)",
        "",
    ]

    for cat in summary.categories:
        priority_icon = {"critical": "🔴", "high": "🟠", "normal": "🟢", "low": "⚪"}.get(
            cat.priority, "🟢"
        )
        lines.append(f"\n## {priority_icon} {cat.category_name} ({cat.unread_count} unread)")

        for email in cat.emails[:5]:
            lines.append(f"- **{email.subject}** - {email.sender.email}")
            lines.append(f"  {email.snippet[:80]}...")

        if cat.total_count > 5:
            lines.append(f"  _...and {cat.total_count - 5} more_")

    if summary.uncategorized:
        lines.append(f"\n## 📋 Other ({len(summary.uncategorized)} emails)")
        for email in summary.uncategorized[:5]:
            lines.append(f"- **{email.subject}** - {email.sender.email}")

    return "\n".join(lines)


def _format_category_summary(summary) -> str:
    """Format category summary for display."""
    lines = [
        f"# {summary.category_name}",
        f"**Total:** {summary.total_count} | **Unread:** {summary.unread_count}",
        "",
    ]

    for email in summary.emails:
        status = "📬" if not email.is_read else "📭"
        lines.append(f"{status} **{email.subject}**")
        lines.append(f"   From: {email.sender.email} | {email.date.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"   {email.snippet[:100]}...")
        lines.append(f"   ID: `{email.id}`")
        lines.append("")

    return "\n".join(lines)


def _format_inbox_stats(stats) -> str:
    """Format inbox stats for display."""
    return f"""
# 📊 Inbox Statistics

- **Total Messages:** {stats.total_messages}
- **Unread:** {stats.unread_count}
- **Starred:** {stats.starred_count}
- **Important (Unread):** {stats.important_count}

_Updated: {stats.updated_at.strftime('%Y-%m-%d %H:%M:%S')}_
"""


def _format_labels(labels: list[dict]) -> str:
    """Format labels list for display."""
    lines = ["# Gmail Labels\n"]
    system_labels = []
    user_labels = []

    for label in labels:
        if label.get("type") == "system":
            system_labels.append(label["name"])
        else:
            user_labels.append(label["name"])

    if user_labels:
        lines.append("## User Labels")
        for name in sorted(user_labels):
            lines.append(f"- {name}")

    if system_labels:
        lines.append("\n## System Labels")
        for name in sorted(system_labels):
            lines.append(f"- {name}")

    return "\n".join(lines)


def _format_categories_config(categories) -> str:
    """Format categories configuration for display."""
    lines = ["# Configured Email Categories\n"]

    for cat in categories.get_all_categories():
        priority_icon = {"critical": "🔴", "high": "🟠", "normal": "🟢", "low": "⚪"}.get(
            cat.priority, "🟢"
        )
        lines.append(f"## {priority_icon} {cat.name}")
        lines.append(f"Key: `{cat.key}` | Priority: {cat.priority}")
        lines.append(f"Description: {cat.description}")

        if cat.matcher.senders:
            lines.append(f"Sender patterns: {', '.join(cat.matcher.senders)}")
        if cat.matcher.subjects:
            lines.append(f"Subject patterns: {', '.join(cat.matcher.subjects)}")
        if cat.matcher.labels:
            lines.append(f"Labels: {', '.join(cat.matcher.labels)}")
        lines.append("")

    return "\n".join(lines)


# ============================================================================
# MAIN
# ============================================================================


def main():
    """Run the MCP server."""
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    logger.info("Starting Gmail MCP Server...")

    async def run():
        try:
            async with stdio_server() as (read_stream, write_stream):
                init_options = server.create_initialization_options()
                await server.run(read_stream, write_stream, init_options)
        except Exception as e:
            logger.exception(f"Error running server: {e}")
            raise

    try:
        asyncio.run(run())
    except Exception as e:
        logger.exception(f"Error in main: {e}")
        raise


if __name__ == "__main__":
    main()
