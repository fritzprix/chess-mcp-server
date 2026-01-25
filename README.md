# ♟️ Chess MCP Server

**Give your AI Agent eyes to see the board and hands to make the move.**

This is not just a chess API. It's a **Model Context Protocol (MCP)** server designed to let Large Language Models (LLMs) like Claude play chess *agentically*. 

Capable of visualizing the board in real-time HTML, understanding spatial relationships via Markdown, and challenging you with a hybrid difficulty engine (Levels 1-10)—or simply facilitating a game between you and your Agent.

## 🚀 Features

-   **MCP-UI Support**: Interactive HTML board embedded directly in the chat (where supported).
-   **Hybrid AI Engine**: Adjustable difficulty from "Random Blunderer" (Level 1) to "Minimax Master" (Level 10).
-   **Agent vs. Agent**: Let two AI personalities battle it out.
-   **Web Dashboard**: Automatically launches a local sidecar dashboard (`http://localhost:8080`) to monitor all active games.

## 📦 Installation

### Prerequisites
-   Python 3.10+
-   An MCP Client (e.g., [Claude Desktop](https://claude.ai/download), [Cursor](https://cursor.sh/))

### 1. Clone & Setup
```bash
git clone https://github.com/your-repo/chess-mcp-server.git
cd chess-mcp-server

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure MCP Client

Add the following to your MCP Client configuration file (e.g., `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "chess": {
      "command": "/absolute/path/to/chess-mcp-server/.venv/bin/python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/absolute/path/to/chess-mcp-server"
    }
  }
}
```

> **Note**: Replace `/absolute/path/to/...` with the full path to where you cloned the repository.

## 🎮 How to Play

Once the server is connected, you can ask your Agent to start a game.

### Start a Game
Ask: *"Start a new chess game against the computer at level 5."*
-   The Agent calls `createGame`.
-   **Pro Tip**: You can also ask *"I want to play against YOU. Create a game where you are White."*

### The Game Loop
1.  **Your Move**:
    -   Interact with the **HTML Board** if shown. Drag your piece and click **Confirm**.
    -   *Or* tell the Agent: *"Move pawn to e4."*
2.  **Agent's Turn**:
    -   The Agent calls `waitForNextTurn`.
    -   It sees the board (Markdown or HTML) and thinks about the move.
    -   It calls `finishTurn` to submit its move.
3.  **Checkmate**:
    -   If you deliver the final blow, you can check the **"Claim Checkmate"** box on the UI or tell the Agent *"Checkmate!"*.

### Dashboard
When the server starts, it will try to open **http://localhost:8080**. You can view the list of all active games and spectator views there.
