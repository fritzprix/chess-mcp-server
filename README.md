# ♟️ Chess MCP Server

**Give your AI Agent eyes to see the board and hands to make the move.**

This is not just a chess API. It's a **Model Context Protocol (MCP)** server designed to let Large Language Models (LLMs) like Claude play chess *agentically*. 

Capable of visualizing the board in real-time HTML, understanding spatial relationships via Markdown, and challenging you with a hybrid difficulty engine (Levels 1-10)—or simply facilitating a game between you and your Agent.

## 🚀 Features

-   **MCP-UI Support**: Interactive HTML board embedded directly in the chat (where supported).
-   **Hybrid AI Engine**: Adjustable difficulty from "Random Blunderer" (Level 1) to "Minimax Master" (Level 10).
-   **Agent vs. Agent**: Let two AI personalities battle it out.
-   **Web Dashboard**: Automatically launches a local sidecar dashboard (`http://localhost:8080`) to monitor all active games.

## 🧰 Tools API

| Tool | Description |
| :--- | :--- |
| `createGame` | Initializes a new chess game session against Computer or another Agent. |
| `joinGame` | Joins an existing game using its Game ID. |
| `finishTurn` | Submits a move (algebraic or UCI) and optionally claims a win. |
| `waitForNextTurn` | Long-polling tool that waits for the opponent's move. |

> For full specification, see [docs/spec/tools.md](docs/spec/tools.md).

## 📦 Installation

### Prerequisites
-   Python 3.10+
-   An MCP Client (e.g., [Claude Desktop](https://claude.ai/download), [Cursor](https://cursor.sh/))

### 1. Installation
You can install directly from PyPI:

```bash
pip install chess-mcp-server
```

### 2. Configure MCP Client

Add the following to your MCP Client configuration file (e.g., `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "chess": {
      "command": "uvx",
      "args": ["chess-mcp-server"]
    }
  }
}
```

*Alternatively, using pip installation:*
```json
{
  "mcpServers": {
    "chess": {
      "command": "python",
      "args": ["-m", "src.mcp_server"]
    }
  }
}
```

## 🛠️ Development

If you want to modify the code:

1.  **Clone & Setup**
    ```bash
    git clone https://github.com/fritzprix/chess-mcp-server.git
    cd chess-mcp-server
    
    python -m venv .venv
    source .venv/bin/activate
    pip install -e .
    ```

## 🎮 How to Play

Once the server is connected, you can ask your Agent to start a game.

### Start a Game
Ask: *"Start a new chess game against the computer at level 5."*
-   The Agent calls `createGame`.
-   **Pro Tip**: You can also ask *"I want to play against YOU. Create a game where you are White."*

### Join an Existing Game
If you have a Game ID (e.g., from another agent), you can ask: *"Join game [Game_ID]"*.
-   The Agent calls `joinGame`.


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
