import argparse

from app.mcp.server import mcp

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport mode: stdio (default for direct CLI/agent run) or sse (for Docker/network service)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host for SSE server")
    parser.add_argument("--port", type=int, default=8000, help="Port for SSE server")
    args = parser.parse_args()

    if args.transport == "sse":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
