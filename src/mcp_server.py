import asyncio
import threading
import webbrowser
import logging
import chess
from typing import Optional, Literal
from mcp.server.fastmcp import FastMCP, Context
import mcp.types as types
from pydantic import BaseModel, Field

# Force absolute imports by ensuring project root is in path
import sys
import os

# Ensure the project root is in sys.path
# This allows 'src.game_state' to be imported reliably
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Absolute imports
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
    type: Literal["computer", "agent", "human"] = Field(..., description="Opponent type. 'computer': Play against AI (No UI). 'agent': Play against another Agent (No UI). 'human': Play against Human (Returns UI)."),
    color: Literal["white", "black"] = Field("white", description="Your color. 'white' moves first. If 'black', the opponent will move first."),
    difficulty: int = Field(5, ge=1, le=10, description="AI Difficulty Level (1-10), if type is 'computer'.")
) -> list:
    """
    Initializes a new chess game session.
    Returns the Game ID and instructions.
    """
    # Construct config dict manually
    # Derive showUi from type
    showUi = (type == "human")
    
    config = {
        "type": type,
        "color": color,
        "showUi": showUi,
        "difficulty": difficulty
    }
    game = manager.create_game(config)
    
    content = []
    
    base_info = (
        f"Game Created Successfully!\n"
        f"- Game ID: {game.id}\n"
        f"- Type: {type}\n"
        f"- You are: {color.title()}\n"
        f"- Difficulty: Level {difficulty} (if computer)\n"
    )

    if color == "white":
        my_color_str = "White"
        md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
        md += f"\n\n🎯 **REQUIRED NEXT ACTION**: Game started! You are White and move first. Review the board state above, select your move, and call `finishTurn(game_id='{game.id}', move='<your_move>')` immediately."
        
        full_text = base_info + "\n" + md
        content.append(types.TextContent(type="text", text=full_text))
            
    else:
        first_move_msg = ""
        if type == "computer":
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(manager._computer_turn(game))
                first_move_msg = " Computer (White) is calculating its first move..."
            except RuntimeError:
                pass
            
            full_text = base_info + f"\n{first_move_msg}\n\n⏳ **REQUIRED NEXT ACTION**: Game started! You are Black. Computer moves first. Call `waitForNextTurn(game_id='{game.id}')` immediately to receive the computer's move."
            content.append(types.TextContent(type="text", text=full_text))
            
        else:
            full_text = base_info + f"\n\n⏳ **REQUIRED NEXT ACTION**: Game started! You are Black. Opponent (White) moves first. Call `waitForNextTurn(game_id='{game.id}')` immediately to wait for the opponent's move."
            content.append(types.TextContent(type="text", text=full_text))
            
            if showUi:
                is_white_perspective = (color == "black")
                html = render_board_to_html(game.board.fen(), game.id, is_white_perspective=is_white_perspective)
                
                resource = types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(
                        uri=f"ui://chess/{game.id}",
                        mimeType="text/html",
                        text=html
                    )
                )
                content.append(resource)

    return content

@mcp.tool()
async def waitForNextTurn(
    game_id: str = Field(..., description="The ID of the active game.")
) -> list:
    """
    Blocks until it is the Agent's turn (or User's turn via Agent proxy).
    Waits up to 30 seconds for the opponent to move.
    """
    game = manager.get_game(game_id)
    if not game:
        raise ValueError(f"Game '{game_id}' not found. Please verify the game_id and retry.")

    try:
        if game.is_game_over:
            return [types.TextContent(type="text", text=f"🏆 Game Over: {game.result}. The game has concluded!")]

        my_color = chess.WHITE if game.config.get("color", "white") == "white" else chess.BLACK
        is_my_turn = (game.board.turn == my_color)
        
        if not is_my_turn:
             try:
                 await asyncio.wait_for(game.move_event.wait(), timeout=30.0)
             except asyncio.TimeoutError:
                 return [types.TextContent(type="text", text=f"⏳ Timeout: No move received from opponent within 30s.\n\n👉 **REQUIRED NEXT ACTION**: Call `waitForNextTurn(game_id='{game.id}')` again immediately to continue waiting.")]
    
    except Exception as e:
        raise RuntimeError(f"Error while waiting for turn in game '{game_id}': {str(e)}\n\n👉 **REQUIRED NEXT ACTION**: Call `waitForNextTurn(game_id='{game_id}')` again to retry waiting.")

    my_color_str = game.config.get("color", "white").title()
    md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
    
    md += f"\n\n🎯 **REQUIRED NEXT ACTION**: Opponent has moved! It is now your turn ({my_color_str}). Review the board state above, select your move in UCI format (e.g. 'e2e4'), and call `finishTurn(game_id='{game.id}', move='<your_move>')` immediately."
    
    content = []
    content.append(types.TextContent(type="text", text=md))
    
    if game.config.get("showUi"):
        is_white = (game.config.get("color", "white") == "white")
        html = render_board_to_html(game.board.fen(), game.id, is_white_perspective=is_white)
        
        resource = types.EmbeddedResource(
            type="resource",
            resource=types.TextResourceContents(
                uri=f"ui://chess/{game.id}",
                mimeType="text/html",
                text=html
            )
        )
        content.append(resource)
        
    return content

@mcp.tool()
async def finishTurn(
    game_id: str = Field(..., description="The ID of the active game."),
    move: str = Field(..., description="The move in UCI format (e.g., 'e2e4')."),
    claim_win: bool = Field(False, description="Set to true if you are claiming Checkmate or Win with this move.")
) -> list:
    """
    Submits a move to the game server.
    """
    try:
        result = await manager.make_move(game_id, move, claim_win)
        game = manager.get_game(game_id)
        agent_color = chess.WHITE if game.config.get("color", "white") == "white" else chess.BLACK
        is_agent_turn = (game.board.turn == agent_color)
    
        content = []
    
        if game and game.is_game_over:
            msg = f"🏆 Move accepted. Game Over: {game.result}. The game has concluded! No further actions needed."
            content.append(types.TextContent(type="text", text=msg))
            return content

        msg = f"✅ Move '{move}' accepted."
        
        if is_agent_turn:
            msg += "\nIt is now your turn again."
            content.append(types.TextContent(type="text", text=msg))
            
            my_color_str = game.config.get("color", "white").title()
            md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
            md += f"\n\n🎯 **REQUIRED NEXT ACTION**: Review the board state above, select your next move in UCI format (e.g. 'e2e4'), and call `finishTurn(game_id='{game.id}', move='<your_move>')` immediately."
            content.append(types.TextContent(type="text", text=md))
        else:
            msg += f"\n\n⏳ **REQUIRED NEXT ACTION**: Your move is complete. Opponent is thinking. Call `waitForNextTurn(game_id='{game.id}')` immediately to wait for the opponent's move."
            content.append(types.TextContent(type="text", text=msg))
            
            if game.config.get("showUi"):
                 agent_color = game.config.get("color", "white")
                 is_white_perspective = (agent_color == "black")
                 html = render_board_to_html(game.board.fen(), game.id, is_white_perspective=is_white_perspective)
                 resource = types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(
                        uri=f"ui://chess/{game.id}",
                        mimeType="text/html",
                        text=html
                    )
                )
                 content.append(resource)

        return content

    except ValueError as e:
        raise ValueError(
            f"❌ Move Failed: '{move}' is invalid or illegal.\n"
            f"Details: {str(e)}\n\n"
            f"👉 **REQUIRED NEXT ACTION**: Review the error details and board state above, select a valid legal move in UCI format (e.g. 'e2e4'), and call `finishTurn(game_id='{game_id}', move='<your_move>')` again immediately to retry!"
        )
    except Exception as e:
        raise RuntimeError(
            f"❌ Error submitting move '{move}': {str(e)}\n\n"
            f"👉 **REQUIRED NEXT ACTION**: Check the game state and call `finishTurn(game_id='{game_id}', move='<your_move>')` again to retry."
        )

@mcp.tool()
def joinGame(
    game_id: str = Field(..., description="The ID of the game to join.")
) -> list:
    """
    Joins an existing chess game.
    Returns the current board state and turn information.
    """
    game = manager.get_game(game_id)
    if not game:
        raise ValueError(f"Game '{game_id}' not found. Please check the game_id and retry.")
    
    content = []
    msg = f"Joined Game '{game.id}' Successfully.\n"
    turn_color = "White" if game.board.turn == chess.WHITE else "Black"
    msg += f"Current Turn: {turn_color}.\n"
    
    my_color_str = game.config.get("color", "white").title() if "color" in game.config else None
    md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
    
    msg += "\n" + md
    
    agent_color = chess.WHITE if game.config.get("color", "white") == "white" else chess.BLACK
    is_my_turn = (game.board.turn == agent_color)
    
    if is_my_turn:
        msg += f"\n\n🎯 **REQUIRED NEXT ACTION**: It is YOUR turn! Review the board state above, decide your move in UCI format (e.g. 'e2e4'), and call `finishTurn(game_id='{game.id}', move='<your_move>')` immediately."
    else:
        msg += f"\n\n⏳ **REQUIRED NEXT ACTION**: It is opponent's turn. Call `waitForNextTurn(game_id='{game.id}')` immediately to wait for their move."
    
    content.append(types.TextContent(type="text", text=msg))
    return content

# --- Entry Point ---

def launch_dashboard_thread():
    """
    Wrapper to start the dashboard in a separate thread.
    """
    try:
        start_dashboard(port=DASHBOARD_PORT)
    except Exception as e:
        print(f"Dashboard server thread exception: {e}", file=sys.stderr)

def main():
    """
    Main entry point for the Chess MCP Server.
    """
    # Start Dashboard
    t = threading.Thread(target=launch_dashboard_thread, daemon=True)
    t.start()
    
    import time
    from src.web_dashboard import get_active_port
    time.sleep(0.5)
    port = get_active_port()

    # Open Browser (Best Effort)
    try:
        webbrowser.open(f"http://localhost:{port}")
    except:
        pass
        
    print(f"Chess MCP Server Running. Dashboard at http://localhost:{port}", file=sys.stderr)
    
    # Run MCP
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
