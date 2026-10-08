"""Back-compat launcher: existing MCP configs run this file. Prefer `mcp-gtm-server`."""
from gtm_mcp.server import main

if __name__ == "__main__":
    main()
