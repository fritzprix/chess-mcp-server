#!/bin/bash

# Ensure we are in the project root
cd "$(dirname "$0")"

# Activate Virtual Environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Virtual environment not found. Please run 'python -m venv .venv' and install requirements first."
    exit 1
fi

echo "Starting MCP Inspector..."
echo "This will launch a web interface to test the Chess Server."

# Run Inspector wrapping the Python server
# Using -y to automatically say yes to installation if needed
npx -y @modelcontextprotocol/inspector python -m src.mcp_server
