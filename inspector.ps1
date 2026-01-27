$ErrorActionPreference = "Stop"

# Ensure we are in the project root
Set-Location $PSScriptRoot

# Run Inspector wrapping the Python server
# Using uv run to execute in the project environment
npx -y @modelcontextprotocol/inspector uv run python -m src.mcp_server
