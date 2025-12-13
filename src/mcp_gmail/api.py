"""REST API for Home Assistant integration."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import Settings, get_categories_config, get_settings
from .gmail_client import GmailClient
from .models import CategorySummary, DailySummary, InboxStats

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Gmail MCP API server...")
    # Initialize client on startup
    get_client()
    yield
    logger.info("Shutting down Gmail MCP API server...")


# Create FastAPI app
app = FastAPI(
    title="Gmail MCP API",
    description="REST API for Gmail integration with Home Assistant",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware for Home Assistant
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Response Models
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    authenticated: bool
    timestamp: datetime


class UnreadCountResponse(BaseModel):
    """Simple unread count for HA sensors."""
    unread: int
    timestamp: datetime


class CategoryCountResponse(BaseModel):
    """Unread count per category for HA sensors."""
    navy: int = 0
    kids: int = 0
    financial: int = 0
    action_required: int = 0
    other: int = 0
    total: int = 0
    timestamp: datetime


class WebhookPayload(BaseModel):
    """Payload sent to Home Assistant webhook."""
    event_type: str
    data: dict


# ============================================================================
# Endpoints
# ============================================================================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    client = get_client()
    return HealthResponse(
        status="ok",
        authenticated=client.auth.is_authenticated(),
        timestamp=datetime.now(timezone.utc),
    )


@app.get("/api/unread", response_model=UnreadCountResponse)
async def get_unread_count():
    """Get unread email count - ideal for Home Assistant sensor."""
    client = get_client()
    try:
        count = await client.get_unread_count()
        return UnreadCountResponse(
            unread=count,
            timestamp=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error(f"Failed to get unread count: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/unread/categories", response_model=CategoryCountResponse)
async def get_category_counts():
    """Get unread counts per category - ideal for Home Assistant sensors."""
    client = get_client()
    try:
        summary = await client.get_daily_summary(lookback_hours=168)  # 1 week

        counts = CategoryCountResponse(
            timestamp=datetime.now(timezone.utc),
            total=summary.unread_emails,
            other=len([e for e in summary.uncategorized if not e.is_read]),
        )

        for cat in summary.categories:
            if cat.category_key == "navy":
                counts.navy = cat.unread_count
            elif cat.category_key == "kids":
                counts.kids = cat.unread_count
            elif cat.category_key == "financial":
                counts.financial = cat.unread_count
            elif cat.category_key == "action_required":
                counts.action_required = cat.unread_count

        return counts
    except Exception as e:
        logger.error(f"Failed to get category counts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats", response_model=InboxStats)
async def get_inbox_stats():
    """Get inbox statistics."""
    client = get_client()
    try:
        return await client.get_inbox_stats()
    except Exception as e:
        logger.error(f"Failed to get inbox stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/summary/daily")
async def get_daily_summary(
    hours: int = Query(default=24, ge=1, le=168),
    include_read: bool = Query(default=False),
):
    """Get daily email summary."""
    client = get_client()
    try:
        summary = await client.get_daily_summary(hours, include_read)
        return summary.model_dump()
    except Exception as e:
        logger.error(f"Failed to get daily summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/summary/daily/text")
async def get_daily_summary_text(
    hours: int = Query(default=24, ge=1, le=168),
    include_read: bool = Query(default=False),
):
    """Get daily summary as formatted text - good for HA notifications."""
    client = get_client()
    try:
        summary = await client.get_daily_summary(hours, include_read)
        return {"text": _format_summary_for_notification(summary)}
    except Exception as e:
        logger.error(f"Failed to get daily summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/summary/category/{category}")
async def get_category_summary(category: str):
    """Get summary for a specific category."""
    client = get_client()
    try:
        summary = await client.get_category_summary(category)
        if summary is None:
            raise HTTPException(status_code=404, detail=f"Unknown category: {category}")
        return summary.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get category summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/webhook/trigger")
async def trigger_webhook(event_type: str = "daily_summary"):
    """Manually trigger a webhook to Home Assistant."""
    global _settings
    if _settings is None:
        _settings = get_settings()

    if not _settings.ha_webhook_url:
        raise HTTPException(status_code=400, detail="Home Assistant webhook URL not configured")

    client = get_client()

    try:
        # Get summary data
        summary = await client.get_daily_summary()

        payload = WebhookPayload(
            event_type=event_type,
            data={
                "total_emails": summary.total_emails,
                "unread_emails": summary.unread_emails,
                "categories": {
                    cat.category_key: {
                        "name": cat.category_name,
                        "unread": cat.unread_count,
                        "total": cat.total_count,
                    }
                    for cat in summary.categories
                },
                "text_summary": _format_summary_for_notification(summary),
                "generated_at": summary.generated_at.isoformat(),
            },
        )

        # Send to Home Assistant
        async with httpx.AsyncClient() as http_client:
            headers = {}
            if _settings.ha_long_lived_token:
                headers["Authorization"] = f"Bearer {_settings.ha_long_lived_token}"

            response = await http_client.post(
                _settings.ha_webhook_url,
                json=payload.model_dump(),
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()

        return {"status": "ok", "message": "Webhook triggered successfully"}

    except httpx.HTTPError as e:
        logger.error(f"Failed to send webhook: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to send webhook: {e}")
    except Exception as e:
        logger.error(f"Error triggering webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Helpers
# ============================================================================


def _format_summary_for_notification(summary: DailySummary) -> str:
    """Format summary for Home Assistant notification."""
    lines = [f"📧 Email Summary ({summary.unread_emails} unread)"]

    for cat in summary.categories:
        if cat.unread_count > 0:
            icon = {"navy": "⚓", "kids": "👶", "financial": "💰", "action_required": "⚠️"}.get(
                cat.category_key, "📌"
            )
            lines.append(f"{icon} {cat.category_name}: {cat.unread_count}")

            # Add top 2 subjects
            for email in cat.emails[:2]:
                lines.append(f"  • {email.subject[:40]}")

    if summary.uncategorized:
        other_unread = sum(1 for e in summary.uncategorized if not e.is_read)
        if other_unread > 0:
            lines.append(f"📋 Other: {other_unread}")

    return "\n".join(lines)


# ============================================================================
# Main
# ============================================================================


def main():
    """Run the API server."""
    import uvicorn

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    uvicorn.run(
        "mcp_gmail.api:app",
        host=settings.mcp_server_host,
        port=settings.mcp_server_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
