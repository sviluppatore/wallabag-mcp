"""wallabag MCP server package."""

from __future__ import annotations

import os
import sys

from mcp.server.fastmcp import FastMCP

from .client import default_client
from .tools import register_tools

mcp = FastMCP("wallabag-mcp")
register_tools(mcp)


def main() -> None:
    """Run the wallabag MCP server over stdio."""
    base_url = os.environ.get("WALLABAG_BASE_URL", "").strip()
    if not base_url:
        print("Error: WALLABAG_BASE_URL is required", file=sys.stderr)
        sys.exit(1)

    timeout_raw = os.environ.get("WALLABAG_TIMEOUT", "20")
    try:
        timeout = float(timeout_raw)
    except ValueError:
        print(f"Error: WALLABAG_TIMEOUT must be a number, got {timeout_raw!r}", file=sys.stderr)
        sys.exit(1)

    default_client.configure(
        base_url=base_url,
        client_id=os.environ.get("WALLABAG_CLIENT_ID"),
        client_secret=os.environ.get("WALLABAG_CLIENT_SECRET"),
        username=os.environ.get("WALLABAG_USERNAME"),
        password=os.environ.get("WALLABAG_PASSWORD"),
        access_token=os.environ.get("WALLABAG_ACCESS_TOKEN"),
        refresh_token=os.environ.get("WALLABAG_REFRESH_TOKEN"),
        timeout=timeout,
    )
    mcp.run(transport="stdio")


__all__ = ["main", "mcp"]
