"""MCP server entry point: registers all tools and picks the transport.

Default transport is stdio. Set MCP_TRANSPORT=streamable-http (plus HOST/PORT)
for hosted deployments.
"""
import argparse
import os

from gtm_mcp import lifecycle_tools, read_tools, write_tools  # noqa: F401 — registers tools on `mcp`
from gtm_mcp.helpers import logger, mcp

VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


def _resolve_transport():
    """Resolve transport, host, port.

    Precedence: CLI flag > env var > default. Default is stdio, matching
    the behavior expected by Claude Desktop, `mcp-gtm-server`,
    and `./run_server.sh`.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--transport", choices=VALID_TRANSPORTS, default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args, _ = parser.parse_known_args()

    transport = args.transport or os.getenv("MCP_TRANSPORT", "stdio")
    if transport not in VALID_TRANSPORTS:
        logger.warning(
            "Invalid MCP_TRANSPORT=%r; falling back to stdio. Valid: %s",
            transport, VALID_TRANSPORTS,
        )
        transport = "stdio"

    host = args.host or os.getenv("HOST", "127.0.0.1")
    port = args.port or int(os.getenv("PORT", "8000"))
    return transport, host, port


def main():
    """Entry point for the MCP GTM server.

    Default transport is stdio — no env vars needed. To run over HTTP
    (e.g. for ContextForge or any hosted gateway), set
    MCP_TRANSPORT=streamable-http and optionally HOST/PORT.
    """
    transport, host, port = _resolve_transport()

    if transport == "stdio":
        logger.info("Starting FastMCP GTM Server (stdio)...")
        mcp.run()
        return

    mcp.settings.host = host
    mcp.settings.port = port

    # The MCP SDK's DNS-rebinding protection rejects any Host header that
    # isn't localhost/127.0.0.1 with "Invalid Host header". That breaks
    # containerized deployments where a gateway reaches us via private DNS
    # (e.g. gtm-mcp.contextforge.internal). MCP_ALLOWED_HOSTS lets the
    # operator pin specific hostnames; if unset, we disable rebinding
    # protection — safe when the listener is only reachable on a private
    # network (security group, VPC, etc.).
    from mcp.server.transport_security import TransportSecuritySettings
    allowed_hosts = [
        h.strip()
        for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",")
        if h.strip()
    ]
    allowed_origins = [
        o.strip()
        for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ]
    if allowed_hosts:
        mcp.settings.transport_security = TransportSecuritySettings(
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
    else:
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    logger.info(
        "Starting FastMCP GTM Server (%s) on %s:%d...", transport, host, port
    )
    mcp.run(transport=transport)


if __name__ == '__main__':
    main()
