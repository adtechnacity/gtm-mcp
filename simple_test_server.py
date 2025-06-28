#!/usr/bin/env python3
"""
Ultra-simple MCP test server to verify Claude connection
"""
import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    TextContent,
    Tool,
)

# Create the server instance
server = Server("simple-test-server")

@server.list_tools()
async def list_tools() -> ListToolsResult:
    """List available tools"""
    return ListToolsResult(
        tools=[
            Tool(
                name="hello",
                description="Say hello",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Name to greet"}
                    },
                    "required": ["name"]
                }
            )
        ]
    )

@server.call_tool()
async def call_tool(request: CallToolRequest) -> CallToolResult:
    """Handle tool calls"""
    if request.name == "hello":
        name = request.arguments.get("name", "World")
        message = f"Hello, {name}! MCP server is working correctly."
        return CallToolResult(
            content=[TextContent(type="text", text=message)]
        )
    else:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unknown tool: {request.name}")]
        )

async def main():
    """Run the server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())