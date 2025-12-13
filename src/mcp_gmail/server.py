"""MCP Server implementation for Gmail with Gemini-compatible tool schemas.

This module implements the MCP (Model Context Protocol) server for Gmail integration.
All tools are designed with strict JSON Schema compliance for Google Gemini compatibility:
- Explicit type annotations on all properties
- No 'Any' types or complex nested objects
- Clear descriptions for all parameters
- Simplified, flattened parameter structures

The server uses a factory pattern to create fresh instances for each connection,
ensuring proper session isolation.
"""

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

# Global client instance (shared across all server instances for efficiency)
_gmail_client: GmailClient | None = None


def get_gmail_client() -> GmailClient:
    """Get or create Gmail client instance.
    
    Returns:
        GmailClient: The initialized Gmail client singleton.
    """
    global _gmail_client
    if _gmail_client is None:
        settings = get_settings()
        categories = get_categories_config(settings)
        _gmail_client = GmailClient(settings, categories)
    return _gmail_client


# ============================================================================
# TOOL DEFINITIONS - Gemini-Compatible Schemas
# ============================================================================

GMAIL_TOOLS = [
    # -------------------------------------------------------------------------
    # Email Search and Retrieval Tools
    # -------------------------------------------------------------------------
    Tool(
        name="gmail_search",
        description="Search emails using Gmail query syntax. Returns a list of matching emails with subject, sender, date, and snippet. Use Gmail search operators like 'from:', 'to:', 'subject:', 'is:unread', 'has:attachment', 'after:', 'before:'.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query string. Examples: 'from:john@example.com', 'subject:meeting is:unread', 'after:2024/01/01 has:attachment'."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of emails to return. Must be between 1 and 100. Default is 20."
                }
            },
            "required": ["query"]
        },
    ),
    Tool(
        name="gmail_list_unread",
        description="List unread emails from the inbox. Optionally filter by a pre-configured category such as navy, kids, financial, or action_required.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category name. Must be one of: navy, kids, financial, action_required. Leave empty for all unread emails."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of emails to return. Default is 20."
                }
            },
            "required": []
        },
    ),
    Tool(
        name="gmail_get_email",
        description="Get the full content of a specific email by its Gmail message ID. Returns subject, sender, recipients, date, labels, and full body text.",
        inputSchema={
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The Gmail message ID obtained from search or list results."
                }
            },
            "required": ["email_id"]
        },
    ),
    # -------------------------------------------------------------------------
    # Summary and Statistics Tools
    # -------------------------------------------------------------------------
    Tool(
        name="gmail_daily_summary",
        description="Generate a summary of recent emails organized by category. Shows unread counts and top emails in each category (Navy, Kids, Financial, Action Items).",
        inputSchema={
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "description": "How many hours back to look for emails. Default is 24 hours."
                },
                "include_read": {
                    "type": "boolean",
                    "description": "Whether to include already-read emails. Default is false (unread only)."
                }
            },
            "required": []
        },
    ),
    Tool(
        name="gmail_category_summary",
        description="Get a summary of unread emails in one specific category. Returns email count and list of emails matching that category.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category to summarize. Must be one of: navy, kids, financial, action_required."
                }
            },
            "required": ["category"]
        },
    ),
    Tool(
        name="gmail_inbox_stats",
        description="Get current inbox statistics including total messages, unread count, starred count, and important message count.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": []
        },
    ),
    # -------------------------------------------------------------------------
    # Label Tools - Simplified Individual Operations
    # -------------------------------------------------------------------------
    Tool(
        name="gmail_list_labels",
        description="List all Gmail labels including both system labels (INBOX, SENT, etc.) and user-created labels. Returns label names and IDs.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": []
        },
    ),
    Tool(
        name="gmail_create_label",
        description="Create a new Gmail label with optional custom colors. Returns the new label's ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "label_name": {
                    "type": "string",
                    "description": "Name for the new label. Use forward slashes for nested labels (e.g., 'Projects/Work')."
                },
                "background_color": {
                    "type": "string",
                    "description": "Hex color code for label background (e.g., '#16a765'). Optional."
                },
                "text_color": {
                    "type": "string",
                    "description": "Hex color code for label text (e.g., '#ffffff'). Optional."
                }
            },
            "required": ["label_name"]
        },
    ),
    Tool(
        name="gmail_delete_label",
        description="Delete a Gmail label by name or ID. Cannot delete system labels. Requires confirmation.",
        inputSchema={
            "type": "object",
            "properties": {
                "label_name": {
                    "type": "string",
                    "description": "Name of the label to delete. Provide either label_name or label_id."
                },
                "label_id": {
                    "type": "string",
                    "description": "ID of the label to delete. Provide either label_name or label_id."
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually delete. Set false to preview what would be deleted."
                }
            },
            "required": ["confirm"]
        },
    ),
    Tool(
        name="gmail_rename_label",
        description="Rename an existing Gmail label. Cannot rename system labels.",
        inputSchema={
            "type": "object",
            "properties": {
                "label_name": {
                    "type": "string",
                    "description": "Current name of the label to rename. Provide either label_name or label_id."
                },
                "label_id": {
                    "type": "string",
                    "description": "ID of the label to rename. Provide either label_name or label_id."
                },
                "new_name": {
                    "type": "string",
                    "description": "New name for the label."
                }
            },
            "required": ["new_name"]
        },
    ),
    Tool(
        name="gmail_add_label_to_messages",
        description="Add a label to one or more messages. Can specify messages by IDs or by search query.",
        inputSchema={
            "type": "object",
            "properties": {
                "label_name": {
                    "type": "string",
                    "description": "Name of the label to add. Provide either label_name or label_id."
                },
                "label_id": {
                    "type": "string",
                    "description": "ID of the label to add. Provide either label_name or label_id."
                },
                "message_ids": {
                    "type": "string",
                    "description": "Comma-separated list of message IDs to add the label to."
                },
                "query": {
                    "type": "string",
                    "description": "Gmail search query to find messages. Alternative to message_ids."
                },
                "max_messages": {
                    "type": "integer",
                    "description": "Maximum messages to modify when using query. Default 100, max 500."
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually modify. Set false to preview."
                }
            },
            "required": ["confirm"]
        },
    ),
    Tool(
        name="gmail_remove_label_from_messages",
        description="Remove a label from one or more messages. Can specify messages by IDs or by search query.",
        inputSchema={
            "type": "object",
            "properties": {
                "label_name": {
                    "type": "string",
                    "description": "Name of the label to remove. Provide either label_name or label_id."
                },
                "label_id": {
                    "type": "string",
                    "description": "ID of the label to remove. Provide either label_name or label_id."
                },
                "message_ids": {
                    "type": "string",
                    "description": "Comma-separated list of message IDs to remove the label from."
                },
                "query": {
                    "type": "string",
                    "description": "Gmail search query to find messages. Alternative to message_ids."
                },
                "max_messages": {
                    "type": "integer",
                    "description": "Maximum messages to modify when using query. Default 100, max 500."
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually modify. Set false to preview."
                }
            },
            "required": ["confirm"]
        },
    ),
    # -------------------------------------------------------------------------
    # Configuration Tools
    # -------------------------------------------------------------------------
    Tool(
        name="gmail_get_categories",
        description="List the configured email categories and their matching rules. Shows how emails are automatically categorized based on sender, subject, and labels.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": []
        },
    ),
    # -------------------------------------------------------------------------
    # Mark as Read Tools - Separated by Input Type
    # -------------------------------------------------------------------------
    Tool(
        name="gmail_mark_as_read_by_ids",
        description="Mark specific emails as read using their message IDs. Requires confirmation to execute.",
        inputSchema={
            "type": "object",
            "properties": {
                "message_ids": {
                    "type": "string",
                    "description": "Comma-separated list of Gmail message IDs to mark as read."
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually mark as read. Set false to preview."
                }
            },
            "required": ["message_ids", "confirm"]
        },
    ),
    Tool(
        name="gmail_mark_as_read_by_query",
        description="Mark emails matching a search query as read. Use Gmail query syntax. Requires confirmation.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query to find emails to mark as read. Examples: 'from:newsletter@example.com', 'older_than:7d is:unread'."
                },
                "max_emails": {
                    "type": "integer",
                    "description": "Maximum number of emails to mark as read. Default 100, max 500."
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually mark as read. Set false to preview what would be marked."
                }
            },
            "required": ["query", "confirm"]
        },
    ),
    # -------------------------------------------------------------------------
    # Send Email Tool
    # -------------------------------------------------------------------------
    Tool(
        name="gmail_send_email",
        description="Send an email. Can send new emails or reply to existing threads. Requires confirmation before sending.",
        inputSchema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Comma-separated list of recipient email addresses."
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line."
                },
                "body": {
                    "type": "string",
                    "description": "Email body text in plain text format."
                },
                "cc": {
                    "type": "string",
                    "description": "Comma-separated list of CC recipient email addresses. Optional."
                },
                "bcc": {
                    "type": "string",
                    "description": "Comma-separated list of BCC recipient email addresses. Optional."
                },
                "reply_to_message_id": {
                    "type": "string",
                    "description": "Message ID to reply to for threading. Optional."
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually send the email. Set false to preview."
                }
            },
            "required": ["to", "subject", "body", "confirm"]
        },
    ),
]


# ============================================================================
# TOOL HANDLER
# ============================================================================


async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls from MCP clients.
    
    Args:
        name: The name of the tool to execute.
        arguments: Dictionary of arguments passed to the tool.
        
    Returns:
        list[TextContent]: List containing the tool's response text.
    """
    client = get_gmail_client()

    try:
        # -----------------------------------------------------------------
        # Email Search and Retrieval
        # -----------------------------------------------------------------
        if name == "gmail_search":
            query = arguments.get("query", "")
            max_results = min(arguments.get("max_results", 20), 100)
            results = await client.search_emails(query, max_results)
            return [TextContent(type="text", text=_format_email_list(results))]

        elif name == "gmail_list_unread":
            category = arguments.get("category")
            max_results = arguments.get("max_results", 20)
            search = SearchQuery(
                is_unread=True,
                category=category,
                max_results=max_results,
            )
            results = await client.list_emails(search)
            return [TextContent(type="text", text=_format_email_list(results))]

        elif name == "gmail_get_email":
            email_id = arguments.get("email_id")
            if not email_id:
                return [TextContent(type="text", text="Error: email_id is required.")]
            email = await client.get_email(email_id)
            return [TextContent(type="text", text=_format_full_email(email))]

        # -----------------------------------------------------------------
        # Summary and Statistics
        # -----------------------------------------------------------------
        elif name == "gmail_daily_summary":
            hours = arguments.get("hours", 24)
            include_read = arguments.get("include_read", False)
            summary = await client.get_daily_summary(hours, include_read)
            return [TextContent(type="text", text=_format_daily_summary(summary))]

        elif name == "gmail_category_summary":
            category = arguments.get("category")
            if not category:
                return [TextContent(type="text", text="Error: category is required. Must be one of: navy, kids, financial, action_required.")]
            summary = await client.get_category_summary(category)
            if summary is None:
                return [TextContent(type="text", text=f"Unknown category: {category}. Valid categories: navy, kids, financial, action_required.")]
            return [TextContent(type="text", text=_format_category_summary(summary))]

        elif name == "gmail_inbox_stats":
            stats = await client.get_inbox_stats()
            return [TextContent(type="text", text=_format_inbox_stats(stats))]

        # -----------------------------------------------------------------
        # Label Management - Individual Operations
        # -----------------------------------------------------------------
        elif name == "gmail_list_labels":
            labels = await client.get_labels()
            return [TextContent(type="text", text=_format_labels_detailed(labels))]

        elif name == "gmail_create_label":
            label_name = arguments.get("label_name")
            if not label_name:
                return [TextContent(type="text", text="Error: label_name is required.")]
            
            # Check if label already exists
            existing = await client.find_label_by_name(label_name)
            if existing:
                return [TextContent(
                    type="text",
                    text=f"Error: A label named '{label_name}' already exists (ID: {existing['id']})."
                )]
            
            background_color = arguments.get("background_color")
            text_color = arguments.get("text_color")
            
            result = await client.create_label(label_name, background_color, text_color)
            if result["success"]:
                label = result["label"]
                return [TextContent(
                    type="text",
                    text=f"Success: Created label '{label['name']}' with ID: {label['id']}"
                )]
            else:
                return [TextContent(type="text", text=f"Error: Failed to create label. {result['error']}")]

        elif name == "gmail_delete_label":
            label_id = arguments.get("label_id")
            label_name = arguments.get("label_name")
            confirm = arguments.get("confirm", False)
            
            if not label_id and not label_name:
                return [TextContent(type="text", text="Error: Provide either label_id or label_name.")]
            
            # Find label by name if ID not provided
            if not label_id:
                label = await client.find_label_by_name(label_name)
                if not label:
                    return [TextContent(type="text", text=f"Error: Label not found: {label_name}")]
                label_id = label["id"]
                found_name = label["name"]
            else:
                found_name = label_name or label_id
            
            if not confirm:
                return [TextContent(
                    type="text",
                    text=f"Preview: Label '{found_name}' (ID: {label_id}) would be deleted. Set confirm=true to proceed."
                )]
            
            result = await client.delete_label(label_id)
            if result["success"]:
                return [TextContent(type="text", text=f"Success: Deleted label '{found_name}'.")]
            else:
                return [TextContent(type="text", text=f"Error: Failed to delete label. {result['error']}")]

        elif name == "gmail_rename_label":
            label_id = arguments.get("label_id")
            label_name = arguments.get("label_name")
            new_name = arguments.get("new_name")
            
            if not new_name:
                return [TextContent(type="text", text="Error: new_name is required.")]
            if not label_id and not label_name:
                return [TextContent(type="text", text="Error: Provide either label_id or label_name.")]
            
            # Find label by name if ID not provided
            if not label_id:
                label = await client.find_label_by_name(label_name)
                if not label:
                    return [TextContent(type="text", text=f"Error: Label not found: {label_name}")]
                label_id = label["id"]
                old_name = label["name"]
            else:
                old_name = label_name or label_id
            
            result = await client.rename_label(label_id, new_name)
            if result["success"]:
                return [TextContent(type="text", text=f"Success: Renamed label '{old_name}' to '{new_name}'.")]
            else:
                return [TextContent(type="text", text=f"Error: Failed to rename label. {result['error']}")]

        elif name == "gmail_add_label_to_messages":
            return await _handle_label_modify(client, arguments, add=True)

        elif name == "gmail_remove_label_from_messages":
            return await _handle_label_modify(client, arguments, add=False)

        # -----------------------------------------------------------------
        # Configuration
        # -----------------------------------------------------------------
        elif name == "gmail_get_categories":
            categories = get_categories_config()
            return [TextContent(type="text", text=_format_categories_config(categories))]

        # -----------------------------------------------------------------
        # Mark as Read
        # -----------------------------------------------------------------
        elif name == "gmail_mark_as_read_by_ids":
            message_ids_str = arguments.get("message_ids", "")
            confirm = arguments.get("confirm", False)
            
            if not message_ids_str:
                return [TextContent(type="text", text="Error: message_ids is required.")]
            
            # Parse comma-separated IDs
            message_ids = [mid.strip() for mid in message_ids_str.split(",") if mid.strip()]
            
            if not message_ids:
                return [TextContent(type="text", text="Error: No valid message IDs provided.")]
            
            if not confirm:
                return [TextContent(
                    type="text",
                    text=f"Preview: {len(message_ids)} email(s) would be marked as read. Set confirm=true to proceed."
                )]
            
            result = await client.mark_as_read(message_ids)
            return [TextContent(
                type="text",
                text=f"Success: Marked {result['success']} email(s) as read."
                + (f" Errors: {result['errors']}" if result['errors'] else "")
            )]

        elif name == "gmail_mark_as_read_by_query":
            query = arguments.get("query", "")
            max_emails = min(arguments.get("max_emails", 100), 500)
            confirm = arguments.get("confirm", False)
            
            if not query:
                return [TextContent(type="text", text="Error: query is required.")]
            
            if not confirm:
                # Preview mode - show what would be marked
                search_results = await client.search_emails(f"{query} is:unread", max_emails)
                if not search_results:
                    return [TextContent(type="text", text=f"No unread emails match the query: {query}")]
                
                lines = [f"Preview: {len(search_results)} email(s) would be marked as read:\n"]
                for email in search_results[:20]:
                    lines.append(f"- {email.subject}")
                    lines.append(f"  From: {email.sender.email}")
                    lines.append(f"  Date: {email.date.strftime('%Y-%m-%d %H:%M')}")
                    lines.append("")
                
                if len(search_results) > 20:
                    lines.append(f"... and {len(search_results) - 20} more\n")
                
                lines.append("Set confirm=true to proceed.")
                return [TextContent(type="text", text="\n".join(lines))]
            else:
                result = await client.mark_as_read_by_query(query, max_emails)
                return [TextContent(
                    type="text",
                    text=f"Success: {result['message']}\nMatched: {result['matched']}, Marked as read: {result['success']}"
                    + (f", Errors: {result['errors']}" if result['errors'] else "")
                )]

        # -----------------------------------------------------------------
        # Send Email
        # -----------------------------------------------------------------
        elif name == "gmail_send_email":
            to_str = arguments.get("to", "")
            subject = arguments.get("subject", "")
            body = arguments.get("body", "")
            cc_str = arguments.get("cc", "")
            bcc_str = arguments.get("bcc", "")
            reply_to_message_id = arguments.get("reply_to_message_id")
            confirm = arguments.get("confirm", False)
            
            # Parse comma-separated addresses
            to = [addr.strip() for addr in to_str.split(",") if addr.strip()]
            cc = [addr.strip() for addr in cc_str.split(",") if addr.strip()] if cc_str else []
            bcc = [addr.strip() for addr in bcc_str.split(",") if addr.strip()] if bcc_str else []
            
            if not to:
                return [TextContent(type="text", text="Error: At least one recipient (to) is required.")]
            if not subject:
                return [TextContent(type="text", text="Error: subject is required.")]
            if not body:
                return [TextContent(type="text", text="Error: body is required.")]
            
            if not confirm:
                lines = [
                    "Preview: The following email would be sent:\n",
                    f"To: {', '.join(to)}",
                ]
                if cc:
                    lines.append(f"CC: {', '.join(cc)}")
                if bcc:
                    lines.append(f"BCC: {', '.join(bcc)}")
                lines.append(f"Subject: {subject}")
                if reply_to_message_id:
                    lines.append(f"Reply to message: {reply_to_message_id}")
                lines.append(f"\n--- Body ---\n{body[:500]}")
                if len(body) > 500:
                    lines.append(f"\n... ({len(body) - 500} more characters)")
                lines.append("\nSet confirm=true to send this email.")
                
                return [TextContent(type="text", text="\n".join(lines))]
            else:
                result = await client.send_email(
                    to=to,
                    subject=subject,
                    body=body,
                    cc=cc if cc else None,
                    bcc=bcc if bcc else None,
                    reply_to_message_id=reply_to_message_id,
                )
                
                if result["success"]:
                    return [TextContent(
                        type="text",
                        text=f"Success: Email sent!\nTo: {', '.join(result['to'])}\nSubject: {result['subject']}\nMessage ID: {result['message_id']}"
                    )]
                else:
                    return [TextContent(type="text", text=f"Error: Failed to send email. {result['error']}")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.exception(f"Error executing tool {name}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def _handle_label_modify(client: GmailClient, arguments: dict[str, Any], add: bool) -> list[TextContent]:
    """Handle add/remove label from messages.
    
    Args:
        client: The Gmail client instance.
        arguments: Tool arguments dictionary.
        add: True to add label, False to remove label.
        
    Returns:
        list[TextContent]: Response text.
    """
    label_id = arguments.get("label_id")
    label_name = arguments.get("label_name")
    message_ids_str = arguments.get("message_ids", "")
    query = arguments.get("query")
    max_messages = min(arguments.get("max_messages", 100), 500)
    confirm = arguments.get("confirm", False)
    
    action_verb = "add" if add else "remove"
    action_prep = "to" if add else "from"
    
    if not label_id and not label_name:
        return [TextContent(type="text", text="Error: Provide either label_id or label_name.")]
    if not message_ids_str and not query:
        return [TextContent(type="text", text="Error: Provide either message_ids or query.")]
    
    # Find label by name if ID not provided
    if not label_id:
        label = await client.find_label_by_name(label_name)
        if not label:
            return [TextContent(type="text", text=f"Error: Label not found: {label_name}")]
        label_id = label["id"]
        label_display = label["name"]
    else:
        label_display = label_name or label_id
    
    # Get message IDs from string or query
    if message_ids_str:
        message_ids = [mid.strip() for mid in message_ids_str.split(",") if mid.strip()]
    else:
        search_results = await client.search_emails(query, max_messages)
        if not search_results:
            return [TextContent(type="text", text=f"No emails found matching query: {query}")]
        message_ids = [email.id for email in search_results]
    
    if not confirm:
        return [TextContent(
            type="text",
            text=f"Preview: Would {action_verb} label '{label_display}' {action_prep} {len(message_ids)} message(s). Set confirm=true to proceed."
        )]
    
    if add:
        result = await client.modify_message_labels(message_ids, add_label_ids=[label_id])
    else:
        result = await client.modify_message_labels(message_ids, remove_label_ids=[label_id])
    
    if result["success"] > 0:
        return [TextContent(
            type="text",
            text=f"Success: {'Added' if add else 'Removed'} label '{label_display}' {action_prep} {result['success']} message(s)."
            + (f" Errors: {result['errors']}" if result['errors'] else "")
        )]
    else:
        return [TextContent(type="text", text=f"Error: Failed to modify labels. {result['errors']}")]


# ============================================================================
# RESOURCES
# ============================================================================

GMAIL_RESOURCES = [
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


async def handle_read_resource(uri: str) -> str:
    """Read a Gmail resource.
    
    Args:
        uri: The resource URI to read.
        
    Returns:
        str: JSON string representation of the resource.
    """
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
# SERVER FACTORY
# ============================================================================


def create_mcp_server() -> Server:
    """Create a new MCP server instance.
    
    This factory function creates a fresh Server instance with all tools
    and resources registered. Use this to ensure each connection gets
    its own server instance for proper session isolation.
    
    Returns:
        Server: A new MCP server instance ready to handle connections.
    """
    server = Server("gmail-mcp")
    
    # Register tool list handler
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return GMAIL_TOOLS
    
    # Register tool call handler
    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return await handle_call_tool(name, arguments)
    
    # Register resource list handler
    @server.list_resources()
    async def list_resources() -> list[Resource]:
        return GMAIL_RESOURCES
    
    # Register resource read handler
    @server.read_resource()
    async def read_resource(uri: str) -> str:
        return await handle_read_resource(uri)
    
    return server


# Legacy: Keep a module-level server for backwards compatibility with stdio mode
server = create_mcp_server()


# ============================================================================
# FORMATTING HELPERS
# ============================================================================


def _format_email_list(emails: list) -> str:
    """Format email list for display.
    
    Args:
        emails: List of email objects to format.
        
    Returns:
        str: Formatted string representation.
    """
    if not emails:
        return "No emails found."

    lines = [f"Found {len(emails)} email(s):\n"]
    for email in emails:
        status = "UNREAD" if not email.is_read else "READ"
        star = " STARRED" if email.is_starred else ""
        attachment = " HAS_ATTACHMENT" if email.has_attachments else ""
        categories = f" [{', '.join(email.categories)}]" if email.categories else ""

        lines.append(
            f"[{status}{star}{attachment}] {email.subject}{categories}\n"
            f"   From: {email.sender}\n"
            f"   Date: {email.date.strftime('%Y-%m-%d %H:%M')}\n"
            f"   ID: {email.id}\n"
            f"   {email.snippet[:100]}...\n"
        )
    return "\n".join(lines)


def _format_full_email(email) -> str:
    """Format full email for display.
    
    Args:
        email: Email object to format.
        
    Returns:
        str: Formatted string representation.
    """
    categories = f"Categories: {', '.join(email.categories)}" if email.categories else ""

    attachments = ""
    if email.attachments:
        att_list = ", ".join(a.filename for a in email.attachments)
        attachments = f"\nAttachments: {att_list}"

    body = email.body_text or "(No text content)"
    if len(body) > 2000:
        body = body[:2000] + "\n\n... [truncated]"

    return f"""
Subject: {email.subject}
From: {email.sender}
To: {', '.join(str(t) for t in email.to)}
Date: {email.date.strftime('%Y-%m-%d %H:%M:%S')}
Labels: {', '.join(email.labels)}
{categories}
{attachments}

---

{body}
"""


def _format_daily_summary(summary) -> str:
    """Format daily summary for display.
    
    Args:
        summary: Daily summary object to format.
        
    Returns:
        str: Formatted string representation.
    """
    lines = [
        "Daily Email Summary",
        f"Period: {summary.period_start.strftime('%Y-%m-%d %H:%M')} to {summary.period_end.strftime('%Y-%m-%d %H:%M')}",
        f"Total Emails: {summary.total_emails} ({summary.unread_emails} unread)",
        "",
    ]

    for cat in summary.categories:
        priority_label = {"critical": "CRITICAL", "high": "HIGH", "normal": "NORMAL", "low": "LOW"}.get(
            cat.priority, "NORMAL"
        )
        lines.append(f"\n[{priority_label}] {cat.category_name} ({cat.unread_count} unread)")

        for email in cat.emails[:5]:
            lines.append(f"- {email.subject} - {email.sender.email}")
            lines.append(f"  {email.snippet[:80]}...")

        if cat.total_count > 5:
            lines.append(f"  ...and {cat.total_count - 5} more")

    if summary.uncategorized:
        lines.append(f"\n[OTHER] Uncategorized ({len(summary.uncategorized)} emails)")
        for email in summary.uncategorized[:5]:
            lines.append(f"- {email.subject} - {email.sender.email}")

    return "\n".join(lines)


def _format_category_summary(summary) -> str:
    """Format category summary for display.
    
    Args:
        summary: Category summary object to format.
        
    Returns:
        str: Formatted string representation.
    """
    lines = [
        f"Category: {summary.category_name}",
        f"Total: {summary.total_count} | Unread: {summary.unread_count}",
        "",
    ]

    for email in summary.emails:
        status = "UNREAD" if not email.is_read else "READ"
        lines.append(f"[{status}] {email.subject}")
        lines.append(f"   From: {email.sender.email} | {email.date.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"   {email.snippet[:100]}...")
        lines.append(f"   ID: {email.id}")
        lines.append("")

    return "\n".join(lines)


def _format_inbox_stats(stats) -> str:
    """Format inbox stats for display.
    
    Args:
        stats: Inbox stats object to format.
        
    Returns:
        str: Formatted string representation.
    """
    return f"""
Inbox Statistics

- Total Messages: {stats.total_messages}
- Unread: {stats.unread_count}
- Starred: {stats.starred_count}
- Important (Unread): {stats.important_count}

Updated: {stats.updated_at.strftime('%Y-%m-%d %H:%M:%S')}
"""


def _format_labels_detailed(labels: list[dict]) -> str:
    """Format labels list with full details for display.
    
    Args:
        labels: List of label dictionaries.
        
    Returns:
        str: Formatted string representation.
    """
    lines = ["Gmail Labels:\n"]
    
    system_labels = []
    user_labels = []
    
    for label in labels:
        if label.get("type") == "system":
            system_labels.append(label)
        else:
            user_labels.append(label)
    
    if system_labels:
        lines.append("System Labels:")
        for label in sorted(system_labels, key=lambda x: x.get("name", "")):
            lines.append(f"  - {label['name']} (ID: {label['id']})")
    
    if user_labels:
        lines.append("\nUser Labels:")
        for label in sorted(user_labels, key=lambda x: x.get("name", "")):
            color_info = ""
            if label.get("color"):
                color_info = f" [color: {label['color'].get('backgroundColor', 'default')}]"
            lines.append(f"  - {label['name']} (ID: {label['id']}){color_info}")
    
    return "\n".join(lines)


def _format_labels(labels: list[dict]) -> str:
    """Format labels list for simple display.
    
    Args:
        labels: List of label dictionaries.
        
    Returns:
        str: Formatted string representation.
    """
    lines = ["Gmail Labels\n"]
    system_labels = []
    user_labels = []

    for label in labels:
        if label.get("type") == "system":
            system_labels.append(label["name"])
        else:
            user_labels.append(label["name"])

    if user_labels:
        lines.append("User Labels:")
        for name in sorted(user_labels):
            lines.append(f"- {name}")

    if system_labels:
        lines.append("\nSystem Labels:")
        for name in sorted(system_labels):
            lines.append(f"- {name}")

    return "\n".join(lines)


def _format_categories_config(categories) -> str:
    """Format categories configuration for display.
    
    Args:
        categories: Categories configuration object.
        
    Returns:
        str: Formatted string representation.
    """
    lines = ["Configured Email Categories\n"]

    for cat in categories.get_all_categories():
        priority_label = {"critical": "CRITICAL", "high": "HIGH", "normal": "NORMAL", "low": "LOW"}.get(
            cat.priority, "NORMAL"
        )
        lines.append(f"[{priority_label}] {cat.name}")
        lines.append(f"Key: {cat.key} | Priority: {cat.priority}")
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
    """Run the MCP server.
    
    Initializes logging and starts the async MCP server loop.
    """
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
