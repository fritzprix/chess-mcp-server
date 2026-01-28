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
    color: Literal["white", "black"] = Field("white", description="Your color. 'white' moves first. If 'black', computer will move first."),
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

    # Scenarios:
    # 1. We are White -> It is OUR turn. Show board, prompt for move.
    # 2. We are Black -> It is Opponent's turn. If Computer, trigger it. Prompt wait.

    if color == "white":
        # My Turn logic
        # Pass player color to rendering
        my_color_str = "White"
        md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
        md += "\n\n**Next Action**: Decide your move and call `finishTurn(game_id, move)`."
        
        full_text = base_info + "\n" + md
        content.append(types.TextContent(type="text", text=full_text))
        
        if showUi:
            is_white = True
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
            
    else:
        # Opponent's Turn logic
        first_move_msg = ""
        if type == "computer":
            # Trigger computer move immediately as it is White
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(manager._computer_turn(game))
                first_move_msg = " Computer (White) is making the first move..."
            except RuntimeError:
                pass
            
            full_text = base_info + f"\n{first_move_msg}\nNext action: Call `waitForNextTurn(game_id='{game.id}')` to start."
            content.append(types.TextContent(type="text", text=full_text))
            
        else:
            # Opponent is Human (or another Agent via Tool, but assuming Human if showUi).
            full_text = base_info + "\nWaiting for Human Opponent to move..."
            content.append(types.TextContent(type="text", text=full_text))
            
            if showUi:
                # Return UI for Human to move
                is_white = (color == "white")
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
            return [types.TextContent(type="text", text=f"Game Over: {game.result}")]

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
                 return [types.TextContent(type="text", text="Timeout: No move received yet. Please call this tool again immediately.")]
    
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error during wait: {str(e)}")]

    # Generate Content
    my_color_str = game.config.get("color", "white").title()
    md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
    
    # Add Guidance
    md += "\n**Next Action**: Decide your move and call `finishTurn(game_id, move)`."
    
    content = []
    content.append(types.TextContent(type="text", text=md))
    
    # 2. UI Resource
    if game.config.get("showUi"):
        # Pass perspective based on config
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
        
        # Check game over after move
        game = manager.get_game(game_id)
        # Determine who just moved and who is next.
        # If I am 'color', and now it is 'color' turn, then Opponent just moved.
        # If now it is NOT 'color' turn, then I just moved.
    
        agent_color = chess.WHITE if game.config.get("color", "white") == "white" else chess.BLACK
        is_agent_turn = (game.board.turn == agent_color)
    
        content = []
    
    # Base text
        if game and game.is_game_over:
            msg = f"Move accepted. Game Over: {game.result}. No further actions needed."
        else:
            msg = f"{result}"
            
        # Determine who just moved and who is next.
        agent_color = chess.WHITE if game.config.get("color", "white") == "white" else chess.BLACK
        is_agent_turn = (game.board.turn == agent_color)
        
        content = []
        
        # Logic for return content
        if is_agent_turn:
            # 1. Opponent (Human checkmated or moved) -> Agent.
            # It is now Agent's turn.
            # Return Text Board so Agent can see state.
            msg += "\nIt is your turn."
            content.append(types.TextContent(type="text", text=msg))
            
            # Return Text Board so Agent can see state.
            # msg += "\nIt is your turn." # Duplicate line removed
            # content.append(msg)
            
            my_color_str = game.config.get("color", "white").title()
            md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
            md += "\n**Next Action**: Decide your move and call `finishTurn(game_id, move)`."
            content.append(types.TextContent(type="text", text=md))
            if game.config.get("showUi"):
                # Return UI for Human to move
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

    except ValueError as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}\nAdvice: Please review the error, check the board state in the previous turn, and try a different move.")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"System Error: {str(e)}")]

# --- Entry Point ---

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
        return ["Error: Game not found"]
    
    content = []
    msg = f"Joined Game {game.id} Successfully.\n"
    
    # Determine whose turn it is
    turn_color = "White" if game.board.turn == chess.WHITE else "Black"
    msg += f"Current Turn: {turn_color}.\n"
    
    # Add Board State
    my_color_str = game.config.get("color", "white").title() if "color" in game.config else None
    md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
    
    msg += "\n" + md
        
    msg += "\n\n**Next Action**: Check if it is your turn. If yes, decide move and call `finishTurn`. If no, call `waitForNextTurn`."
    
    content.append(types.TextContent(type="text", text=msg))
    return content

# --- Entry Point ---

def launch_dashboard_thread():
    """
    Wrapper to start the dashboard in a separate thread.
    """
    start_dashboard(port=DASHBOARD_PORT)

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
        
    print(f"Chess MCP Server Running. Dashboard at http://localhost:{DASHBOARD_PORT}", file=sys.stderr)
    
    # Run MCP
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
