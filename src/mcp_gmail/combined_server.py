"""Combined server that runs both REST API and MCP SSE endpoints.

This is the recommended way to deploy the Gmail MCP server, as it exposes:
- REST API endpoints for Home Assistant at /api/*
- MCP SSE endpoint for Claude Desktop at /mcp/sse
- Health check at /health
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from .config import Settings, get_categories_config, get_settings
from .gmail_client import GmailClient
from .server import server as mcp_server  # The MCP Server instance

logger = logging.getLogger(__name__)

# Global client
_gmail_client: Optional[GmailClient] = None
_settings: Optional[Settings] = None


def get_client() -> GmailClient:
    """Get Gmail client instance."""
    global _gmail_client, _settings
    if _gmail_client is None:
        _settings = get_settings()
        categories = get_categories_config(_settings)
        _gmail_client = GmailClient(_settings, categories)
    return _gmail_client


# SSE transport for MCP
sse = SseServerTransport("/mcp/messages/")


async def handle_sse(request: Request) -> Response:
    """Handle SSE connections from MCP clients (Claude Desktop)."""
    logger.info(f"New MCP SSE connection from {request.client}")
    
    async with sse.connect_sse(
        request.scope, 
        request.receive, 
        request._send
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )
    
    return Response()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Gmail MCP Combined Server...")
    logger.info("  - REST API: /api/*")
    logger.info("  - MCP SSE: /mcp/sse")
    # Initialize Gmail client on startup
    get_client()
    yield
    logger.info("Shutting down Gmail MCP Combined Server...")


# Create FastAPI app
app = FastAPI(
    title="Gmail MCP Server",
    description="Combined REST API and MCP SSE server for Gmail",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the MCP SSE routes
app.mount("/mcp/messages", sse.handle_post_message)
app.add_api_route("/mcp/sse", handle_sse, methods=["GET"])


# ============================================================================
# Health Check
# ============================================================================


@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        client = get_client()
        authenticated = client.authenticate()
        return {
            "status": "ok",
            "authenticated": authenticated,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "services": {
                "rest_api": True,
                "mcp_sse": True,
            }
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "degraded",
            "authenticated": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
        }


# ============================================================================
# REST API Endpoints (for Home Assistant)
# ============================================================================


@app.get("/api/unread")
async def get_unread_count():
    """Get unread email count."""
    client = get_client()
    stats = await client.get_inbox_stats()
    return {
        "unread": stats.unread_count,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/unread/categories")
async def get_category_counts():
    """Get unread counts by category."""
    client = get_client()
    summary = await client.get_daily_summary(hours=24, include_read=False)
    
    counts = {
        "navy": 0,
        "kids": 0,
        "financial": 0,
        "action_required": 0,
        "other": 0,
        "total": 0,
    }
    
    for cat in summary.categories:
        key = cat.category_key
        if key in counts:
            counts[key] = cat.unread_count
    
    counts["other"] = sum(1 for e in summary.uncategorized if not e.is_read)
    counts["total"] = summary.unread_emails
    counts["timestamp"] = datetime.now(timezone.utc).isoformat()
    
    return counts


@app.get("/api/summary/daily")
async def get_daily_summary(hours: int = 24, include_read: bool = False):
    """Get daily email summary."""
    client = get_client()
    summary = await client.get_daily_summary(hours=hours, include_read=include_read)
    return summary.model_dump()


@app.get("/api/summary/daily/text")
async def get_daily_summary_text(hours: int = 24, include_read: bool = False):
    """Get daily email summary as formatted text."""
    client = get_client()
    summary = await client.get_daily_summary(hours=hours, include_read=include_read)
    
    lines = [f"📧 Email Summary ({summary.unread_emails} unread)"]

    for cat in summary.categories:
        if cat.unread_count > 0:
            icon = {"navy": "⚓", "kids": "👶", "financial": "💰", "action_required": "⚠️"}.get(
                cat.category_key, "📌"
            )
            lines.append(f"{icon} {cat.category_name}: {cat.unread_count}")

            for email in cat.emails[:2]:
                lines.append(f"  • {email.subject[:40]}")

    if summary.uncategorized:
        other_unread = sum(1 for e in summary.uncategorized if not e.is_read)
        if other_unread > 0:
            lines.append(f"📋 Other: {other_unread}")

    return {"text": "\n".join(lines), "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/stats")
async def get_inbox_stats():
    """Get inbox statistics."""
    client = get_client()
    stats = await client.get_inbox_stats()
    return stats.model_dump()


# ============================================================================
# Main
# ============================================================================


def main():
    """Run the combined server."""
    import uvicorn

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info(f"Starting Gmail MCP Combined Server on http://{settings.mcp_server_host}:{settings.mcp_server_port}")
    logger.info(f"  REST API: http://{settings.mcp_server_host}:{settings.mcp_server_port}/api/*")
    logger.info(f"  MCP SSE:  http://{settings.mcp_server_host}:{settings.mcp_server_port}/mcp/sse")

    uvicorn.run(
        app,
        host=settings.mcp_server_host,
        port=settings.mcp_server_port,
    )


if __name__ == "__main__":
    main()
