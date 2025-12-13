"""SSE (Server-Sent Events) transport for MCP server.

This allows Claude Desktop to connect over HTTP/SSE instead of stdio.
Based on the official MCP Python SDK SSE examples.
"""

import logging

from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from .config import get_settings
from .server import server  # Import the configured MCP server instance

logger = logging.getLogger(__name__)

# Create SSE transport instance - the endpoint is where clients POST messages
sse = SseServerTransport("/messages/")


async def handle_sse(request: Request) -> Response:
    """Handle SSE connections from MCP clients."""
    logger.info(f"New SSE connection from {request.client}")
    
    async with sse.connect_sse(
        request.scope, 
        request.receive, 
        request._send
    ) as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options(),
        )
    
    # Return empty response to avoid NoneType error after SSE connection ends
    return Response()


# Create Starlette app with SSE routes
app = Starlette(
    debug=True,
    routes=[
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
        Route("/health", endpoint=lambda r: Response(
            content='{"status": "ok", "transport": "sse"}',
            media_type="application/json"
        ), methods=["GET"]),
    ],
)


def main():
    """Run the MCP SSE server."""
    import uvicorn

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run on a different port than the REST API (8002 for SSE)
    port = int(settings.mcp_server_port) + 2  # REST=8000, SSE=8002

    logger.info(f"Starting MCP SSE server on http://{settings.mcp_server_host}:{port}")
    logger.info(f"SSE endpoint: http://{settings.mcp_server_host}:{port}/sse")

    uvicorn.run(
        app,
        host=settings.mcp_server_host,
        port=port,
    )


if __name__ == "__main__":
    main()
