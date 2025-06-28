#!/bin/bash
# Convenience script to run the MCP GTM server with uv

# Ensure uv is available
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.local/bin/env
fi

# Make sure we're in the right directory
cd "$(dirname "$0")"

# Install dependencies if needed
if [ ! -d ".venv" ]; then
    echo "Installing dependencies with uv..."
    uv sync
fi

# Run the server
echo "Starting MCP GTM Server..."
uv run python server.py