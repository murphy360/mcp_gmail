"""MCP Server implementation for Gmail."""

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    TextContent,
    Tool,
)

from .config import Settings, get_categories_config, get_settings
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
# TOOLS
# ============================================================================


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available Gmail tools."""
    return [
        Tool(
            name="gmail_search",
            description="Search emails using Gmail query syntax or natural language. "
            "Examples: 'from:john@example.com', 'subject:meeting', 'is:unread'",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query or natural language search",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default: 20, max: 100)",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="gmail_list_unread",
            description="List unread emails, optionally filtered by category. "
            "Categories: navy, kids, financial, action_required",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Filter by category (navy, kids, financial, action_required)",
                        "enum": ["navy", "kids", "financial", "action_required"],
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 20,
                    },
                },
            },
        ),
        Tool(
            name="gmail_get_email",
            description="Get the full content of a specific email by its ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": "The Gmail message ID",
                    },
                },
                "required": ["email_id"],
            },
        ),
        Tool(
            name="gmail_daily_summary",
            description="Generate a daily summary of emails organized by category "
            "(Navy, Kids, Financial, Action Items)",
            inputSchema={
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "How many hours back to look (default: 24)",
                        "default": 24,
                    },
                    "include_read": {
                        "type": "boolean",
                        "description": "Include already read emails (default: false)",
                        "default": False,
                    },
                },
            },
        ),
        Tool(
            name="gmail_category_summary",
            description="Get a summary of unread emails in a specific category",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Category to summarize",
                        "enum": ["navy", "kids", "financial", "action_required"],
                    },
                },
                "required": ["category"],
            },
        ),
        Tool(
            name="gmail_inbox_stats",
            description="Get current inbox statistics (unread count, starred, etc.)",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="gmail_get_labels",
            description="List all Gmail labels/folders",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="gmail_get_categories",
            description="List configured email categories and their matching rules",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="gmail_mark_as_read",
            description="Mark emails as read. Can mark specific emails by ID or bulk mark by search query. "
            "Examples: 'from:newsletter@example.com', 'older_than:7d is:unread', 'subject:promotion'",
            inputSchema={
                "type": "object",
                "properties": {
                    "message_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of specific Gmail message IDs to mark as read",
                    },
                    "query": {
                        "type": "string",
                        "description": "Gmail search query to find emails to mark as read (e.g., 'from:newsletter@example.com older_than:7d')",
                    },
                    "max_emails": {
                        "type": "integer",
                        "description": "Maximum number of emails to mark as read when using query (safety limit, default: 100, max: 500)",
                        "default": 100,
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually mark emails as read. Set to false to preview what would be marked.",
                        "default": False,
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    client = get_gmail_client()

    try:
        if name == "gmail_search":
            query = arguments.get("query", "")
            max_results = arguments.get("max_results", 20)
            results = await client.search_emails(query, max_results)
            return [
                TextContent(
                    type="text",
                    text=_format_email_list(results),
                )
            ]

        elif name == "gmail_list_unread":
            category = arguments.get("category")
            max_results = arguments.get("max_results", 20)
            search = SearchQuery(
                is_unread=True,
                category=category,
                max_results=max_results,
            )
            results = await client.list_emails(search)
            return [
                TextContent(
                    type="text",
                    text=_format_email_list(results),
                )
            ]

        elif name == "gmail_get_email":
            email_id = arguments.get("email_id")
            if not email_id:
                return [TextContent(type="text", text="Error: email_id is required")]
            email = await client.get_email(email_id)
            return [
                TextContent(
                    type="text",
                    text=_format_full_email(email),
                )
            ]

        elif name == "gmail_daily_summary":
            hours = arguments.get("hours", 24)
            include_read = arguments.get("include_read", False)
            summary = await client.get_daily_summary(hours, include_read)
            return [
                TextContent(
                    type="text",
                    text=_format_daily_summary(summary),
                )
            ]

        elif name == "gmail_category_summary":
            category = arguments.get("category")
            if not category:
                return [TextContent(type="text", text="Error: category is required")]
            summary = await client.get_category_summary(category)
            if summary is None:
                return [TextContent(type="text", text=f"Unknown category: {category}")]
            return [
                TextContent(
                    type="text",
                    text=_format_category_summary(summary),
                )
            ]

        elif name == "gmail_inbox_stats":
            stats = await client.get_inbox_stats()
            return [
                TextContent(
                    type="text",
                    text=_format_inbox_stats(stats),
                )
            ]

        elif name == "gmail_get_labels":
            labels = await client.get_labels()
            return [
                TextContent(
                    type="text",
                    text=_format_labels(labels),
                )
            ]

        elif name == "gmail_get_categories":
            categories = get_categories_config()
            return [
                TextContent(
                    type="text",
                    text=_format_categories_config(categories),
                )
            ]

        elif name == "gmail_mark_as_read":
            message_ids = arguments.get("message_ids", [])
            query = arguments.get("query")
            max_emails = min(arguments.get("max_emails", 100), 500)  # Cap at 500 for safety
            confirm = arguments.get("confirm", False)
            
            # Validate input
            if not message_ids and not query:
                return [TextContent(
                    type="text",
                    text="Error: Must provide either 'message_ids' or 'query' to specify which emails to mark as read."
                )]
            
            # If using query, first show what would be affected
            if query:
                if not confirm:
                    # Preview mode - show what would be marked
                    search_results = await client.search_emails(f"{query} is:unread", max_emails)
                    if not search_results:
                        return [TextContent(
                            type="text",
                            text=f"No unread emails match the query: {query}"
                        )]
                    
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
                    
                    lines.append("To proceed, call this tool again with confirm=true")
                    
                    return [TextContent(type="text", text="\n".join(lines))]
                else:
                    # Actually mark as read
                    result = await client.mark_as_read_by_query(query, max_emails)
                    return [TextContent(
                        type="text",
                        text=f"✅ {result['message']}\n\nMatched: {result['matched']}\nMarked as read: {result['success']}"
                        + (f"\nErrors: {result['errors']}" if result['errors'] else "")
                    )]
            else:
                # Mark specific message IDs
                if not confirm:
                    return [TextContent(
                        type="text",
                        text=f"⚠️ Preview: {len(message_ids)} email(s) would be marked as read.\n\nTo proceed, call this tool again with confirm=true"
                    )]
                else:
                    result = await client.mark_as_read(message_ids)
                    return [TextContent(
                        type="text",
                        text=f"✅ Marked {result['success']} email(s) as read."
                        + (f"\nErrors: {result['errors']}" if result['errors'] else "")
                    )]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.exception(f"Error executing tool {name}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


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

    print("DEBUG: MCP Server starting...", file=sys.stderr, flush=True)
    logger.info("Starting Gmail MCP Server...")

    async def run():
        print("DEBUG: Entering async run", file=sys.stderr, flush=True)
        try:
            async with stdio_server() as (read_stream, write_stream):
                print("DEBUG: stdio_server connected", file=sys.stderr, flush=True)
                init_options = server.create_initialization_options()
                print(f"DEBUG: init_options created: {init_options}", file=sys.stderr, flush=True)
                await server.run(read_stream, write_stream, init_options)
                print("DEBUG: server.run completed", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"DEBUG: Exception in run: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            raise

    try:
        asyncio.run(run())
    except Exception as e:
        print(f"DEBUG: Exception in main: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
