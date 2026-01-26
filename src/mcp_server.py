import asyncio
import threading
import webbrowser
import logging
from typing import Optional, Literal
from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field

# We use relative imports assuming this is run as a module (python -m src.mcp_server)
# or ensure PYTHONPATH is set.
try:
    from .game_state import GameManager
    from .rendering import render_board_to_markdown, render_board_to_html
    from .web_dashboard import start_dashboard
except ImportError:
    # Fallback for direct execution if path not set
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.game_state import GameManager
    from src.rendering import render_board_to_markdown, render_board_to_html
    from src.web_dashboard import start_dashboard

# Initialize FastMCP
mcp = FastMCP("Chess Server")
manager = GameManager()
DASHBOARD_PORT = 8080

# --- Tools ---

@mcp.tool()
def createGame(
    type: Literal["computer", "agent"] = Field(..., description="Play against 'computer' (AI) or 'agent' (another tool/human)"),
    color: Literal["white", "black"] = Field("white", description="Your color. 'white' moves first. If 'black', computer will move first."),
    showUi: bool = Field(False, description="If true, returns an interactive HTML board in waitForNextTurn. Required for human players."),
    difficulty: int = Field(5, ge=1, le=10, description="AI Difficulty Level (1-10), if type is 'computer'.")
) -> str:
    """
    Initializes a new chess game session.
    Returns the Game ID and instructions.
    """
    # Construct config dict manually
    config = {
        "type": type,
        "color": color,
        "showUi": showUi,
        "difficulty": difficulty
    }
    game = manager.create_game(config)
    
    # Logic: If Player chose Black against Computer, Computer must move NOW (White).
    first_move_msg = ""
    if type == "computer" and color == "black":
        # Trigger computer move immediately as it is White
        try:
             loop = asyncio.get_running_loop()
             loop.create_task(manager._computer_turn(game))
             first_move_msg = " Computer (White) is making the first move..."
        except RuntimeError:
             pass

    info = (
        f"Game Created Successfully!\n"
        f"- Game ID: {game.id}\n"
        f"- Type: {type}\n"
        f"- You are: {color.title()}\n"
        f"- Difficulty: Level {difficulty} (if computer)\n\n"
        f"{first_move_msg}\n"
        f"Next action: Call `waitForNextTurn(game_id='{game.id}')` to start."
    )
    return info

@mcp.tool()
async def waitForNextTurn(
    game_id: str = Field(..., description="The ID of the active game.")
) -> list:
    """
    Blocks until it is the Agent's turn (or User's turn via Agent proxy).
    Waits up to 30 seconds for the opponent to move.
    
    Returns:
    - Board state (Markdown)
    - UI Board (HTML) if showUi is true
    - Or 'Timeout' message if no move happens.
    """
    game = manager.get_game(game_id)
    if not game:
        return ["Error: Game not found"]

    try:
        # Check if game over immediately
        if game.is_game_over:
            return [f"Game Over: {game.result}"]

        # --- Side Logic ---
        # If I am 'color', is it my turn?
        my_color = chess.WHITE if game.config.get("color", "white") == "white" else chess.BLACK
        is_my_turn = (game.board.turn == my_color)
        
        # If it is NOT my turn, I should probably wait.
        if not is_my_turn:
             # It's opponent's turn.
             # Wait for move event.
             try:
                 await asyncio.wait_for(game.move_event.wait(), timeout=30.0)
             except asyncio.TimeoutError:
                 return ["Timeout: No move received yet. Please call this tool again immediately."]
    
    except Exception as e:
        return [f"Error during wait: {str(e)}"]

    # Generate Content
    md = render_board_to_markdown(game.board.fen())
    
    # Add Guidance
    md += "\n\n**Next Action**: Decide your move and call `finishTurn(game_id, move)`."
    
    content = []
    content.append(md)
    
    # 2. UI Resource
    if game.config.get("showUi"):
        # Pass perspective based on config
        is_white = (game.config.get("color", "white") == "white")
        html = render_board_to_html(game.board.fen(), game.id, is_white_perspective=is_white)
        
        resource = {
            "type": "resource",
            "resource": {
                "uri": f"ui://chess/{game.id}",
                "mimeType": "text/html",
                "text": html
            }
        }
        content.append(resource)
        
    return content

@mcp.tool()
async def finishTurn(
    game_id: str = Field(..., description="The ID of the active game."),
    move: str = Field(..., description="The move in UCI format (e.g., 'e2e4')."),
    claim_win: bool = Field(False, description="Set to true if you are claiming Checkmate or Win with this move.")
) -> str:
    """
    Submits a move to the game server.
    """
    try:
        result = await manager.make_move(game_id, move, claim_win)
        
        # Check game over after move
        game = manager.get_game(game_id)
        if game and game.is_game_over:
            return f"Move accepted. Game Over: {game.result}. No further actions needed."
            
        return f"{result}\nNext action: Call `waitForNextTurn(game_id='{game_id}')` to wait for opponent's move."
    except ValueError as e:
        return f"Error: {str(e)}\nAdvice: Please review the error, check the board state in the previous turn, and try a different move."
    except Exception as e:
        return f"System Error: {str(e)}"

# --- Entry Point ---

# --- Entry Point ---

def main():
    """
    Main entry point for the Chess MCP Server.
    """
    # Start Dashboard
    t = threading.Thread(target=launch_dashboard_thread, daemon=True)
    t.start()
    
    # Open Browser (Best Effort)
    try:
        webbrowser.open(f"http://localhost:{DASHBOARD_PORT}")
    except:
        pass
        
    print(f"Chess MCP Server Running. Dashboard at http://localhost:{DASHBOARD_PORT}")
    
    # Run MCP
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
