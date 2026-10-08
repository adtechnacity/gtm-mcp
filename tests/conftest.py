import pytest
from mcp.server.fastmcp.exceptions import ToolError


async def tool_error(coro) -> str:
    """Await a tool call that must fail; return the MCP error message."""
    with pytest.raises(ToolError) as exc:
        await coro
    return str(exc.value)
