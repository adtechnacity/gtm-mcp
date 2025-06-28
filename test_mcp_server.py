#!/usr/bin/env python3
"""
Simple test MCP server to verify Claude connection
"""
import asyncio
import json
import logging
from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequest,
    CallToolResult,
    ListToolsRequest,
    ListToolsResult,
    TextContent,
    Tool,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test-mcp-server")

class TestMCPServer:
    def __init__(self):
        self.server = Server("test-mcp-server")
        self._register_handlers()

    def _register_handlers(self):
        @self.server.list_tools()
        async def handle_list_tools() -> ListToolsResult:
            return ListToolsResult(
                tools=[
                    Tool(
                        name="test_connection",
                        description="Test if MCP server is working",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "message": {"type": "string", "description": "Test message"}
                            },
                            "required": ["message"]
                        }
                    ),
                    Tool(
                        name="check_environment",
                        description="Check the server environment",
                        inputSchema={
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    )
                ]
            )

        @self.server.call_tool()
        async def handle_call_tool(request: CallToolRequest) -> CallToolResult:
            try:
                if request.name == "test_connection":
                    message = request.arguments.get("message", "Hello from MCP!")
                    result = {
                        "status": "success",
                        "message": f"Received: {message}",
                        "server": "test-mcp-server",
                        "version": "1.0.0"
                    }
                    return CallToolResult(
                        content=[TextContent(type="text", text=json.dumps(result, indent=2))]
                    )
                
                elif request.name == "check_environment":
                    import os
                    import sys
                    result = {
                        "python_version": sys.version,
                        "working_directory": os.getcwd(),
                        "environment_variables": {
                            "PATH": os.environ.get("PATH", "Not found"),
                            "HOME": os.environ.get("HOME", "Not found"),
                            "USER": os.environ.get("USER", "Not found")
                        },
                        "python_path": sys.path[:3]  # First 3 entries
                    }
                    return CallToolResult(
                        content=[TextContent(type="text", text=json.dumps(result, indent=2))]
                    )
                
                else:
                    raise ValueError(f"Unknown tool: {request.name}")

            except Exception as e:
                logger.error(f"Error calling tool {request.name}: {str(e)}")
                return CallToolResult(
                    content=[TextContent(type="text", text=f"Error: {str(e)}")]
                )

    async def run(self):
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="test-mcp-server",
                    server_version="1.0.0",
                    capabilities=self.server.get_capabilities(),
                ),
            )

if __name__ == "__main__":
    server = TestMCPServer()
    asyncio.run(server.run())