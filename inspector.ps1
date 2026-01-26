$ErrorActionPreference = "Stop"

# Ensure we are in the project root
Set-Location $PSScriptRoot

# Activate Virtual Environment
if (Test-Path ".venv") {
    Write-Host "Activating virtual environment..."
    & ".\.venv\Scripts\Activate.ps1"
} else {
    Write-Error "Virtual environment not found. Please run 'python -m venv .venv' and install requirements first."
}

Write-Host "Starting MCP Inspector..."
Write-Host "This will launch a web interface to test the Chess Server."

# Run Inspector wrapping the Python server
# Using -y to automatically say yes to installation if needed
npx -y @modelcontextprotocol/inspector python -m src.mcp_server
