#!/bin/bash
# Run the MCP GTM server over stdio with uv (installs deps on first run).
cd "$(dirname "$0")" && exec uv run mcp-gtm-server
