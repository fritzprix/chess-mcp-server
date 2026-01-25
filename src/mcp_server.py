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

# --- Pydantic Models for Tools ---

class GameConfig(BaseModel):
    type: Literal["computer", "agent"] = Field(..., description="Play against 'computer' (AI) or 'agent' (another tool/human)")
    showUi: bool = Field(False, description="If true, returns an interactive HTML board in waitForNextTurn. Required for human players.")
    difficulty: int = Field(5, ge=1, le=10, description="AI Difficulty Level (1-10), if type is 'computer'.")

class WaitForTurnRequest(BaseModel):
    game_id: str = Field(..., description="The ID of the active game.")

class FinishTurnRequest(BaseModel):
    game_id: str = Field(..., description="The ID of the active game.")
    move: str = Field(..., description="The move in UCI format (e.g., 'e2e4').")
    claim_win: bool = Field(False, description="Set to true if you are claiming Checkmate or Win with this move.")

# --- Background Helper ---

def launch_dashboard_thread():
    try:
        start_dashboard(port=DASHBOARD_PORT)
    except Exception as e:
        print(f"Failed to start dashboard: {e}")

# --- Tools ---

@mcp.tool()
def createGame(config: GameConfig) -> str:
    """
    Initializes a new chess game session.
    Returns the Game ID and instructions.
    """
    # Convert Pydantic model to dict
    game = manager.create_game(config.model_dump())
    
    info = (
        f"Game Created Successfully!\n"
        f"- Game ID: {game.id}\n"
        f"- Type: {config.type}\n"
        f"- Difficulty: Level {config.difficulty} (if computer)\n\n"
        f"Next action: Call `waitForNextTurn(game_id='{game.id}')` to start."
    )
    return info

@mcp.tool()
async def waitForNextTurn(game_id: str, ctx: Context = None) -> list:
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

    # If it is NOT my turn (i.e. opponent is moving), we wait.
    # But "My Turn" is ambiguous if Agent is White or Black.
    # Assumption: Agent plays whichever side is currently "To Move", UNLESS it's computer's turn.
    # Actually, in Agent vs Computer:
    # - If Human is White: It is White's turn? Return immediately.
    # - If Human is Black (Computer moved): It is Black's turn? Return immediately.
    # - If Computer is thinking: We block?
    
    # We implement "Long Polling":
    # If the game was just updated (we have a fresh state appropriate for the caller), return.
    # Generally, calling waitForNextTurn implies "I want to know when I can move".
    
    # Simple Logic:
    # If current turn matches the "User/Agent" side? Return.
    # If current turn matches "Computer"? Wait.
    
    # But for "Agent vs Agent", who is who?
    # Spec says: "Blocks execution until it is the Agent's turn to move".
    # This implies we wait for a CHANGE.
    
    # Let's rely on the Event.
    # We optimistically return if it IS our turn (based on flow).
    # But how do we know if we already saw this state?
    # Stateless tool calls.
    # So we simply wait IF logic dictates we should wait for opponent.
    
    # Logic:
    # 1. If Game Over -> Return Result.
    # 2. If vs Computer:
    #    - If Computer Turn -> Wait.
    #    - If Human Turn -> Return.
    # 3. If vs Agent:
    #    - We don't know which agent is which.
    #    - We just use the 30s timeout as a "Refresh".
    #    - Let's check the event. If unset, maybe wait a bit?
    #    - Actually, for Agent vs Agent, usually they take turns calling finishTurn -> waitForNextTurn.
    #    - So usually `waitForNextTurn` is called IMMEDIATELY after `finishTurn`.
    #    - Checks: "Did opponent move?"
    
    # Refined Logic based on spec "Blocks... for up to 30 seconds":
    try:
        # Check if game over immediately
        if game.is_game_over:
            return [f"Game Over: {game.result}"]

        # If computer is playing and it's computer's turn, wait for it to move
        if game.config.get("type") == "computer":
             # If formatted properly, `game_state` triggers computer move in background.
             # We just wait for the event.
             # But if it's ALREADY user's turn (e.g. invalid move previously, or just started as White), return immediate.
            
            # Determine if we should wait
            # If playing White and it's White's turn -> Go.
            # If playing White and it's Black's turn (Computer) -> Wait.
            
            # Since we don't explicitly store "Who is Agent (White/Black)", we assume Agent is the one intiating the game (usually White).
            # But let's assume standard flow.
            
            # If internal AI is thinking, we wait.
            # We can check `game.move_event`. 
            # If we call wait_for() on an event that is NOT set, we block.
            # If it IS set, we return.
            
            # But `move_event` is cleared after set.
            # So if we arrive LATE (event already happened), we might block forever?
            # No, if we arrive late, the BOARD STATE has changed.
            # So we check state first.
            
            pass 
            # Actually, simplest is:
            # Wait for 30s for the *event* ONLY IF it is likely we are waiting (e.g. Computer Turn).
            # If it is Player Turn, we return immediately.
            
            is_computer_turn = (game.config.get("type") == "computer") and (
                (game.board.turn == chess.BLACK) # Assuming Agent=White. Limit for now.
                # TODO: Support Agent=Black config? Spec didn't specify. Assume Agent=White.
            )
            
            if is_computer_turn:
                 # Wait for computer
                 try:
                     await asyncio.wait_for(game.move_event.wait(), timeout=30.0)
                 except asyncio.TimeoutError:
                     return ["Timeout: No move received yet. Please call this tool again immediately."]
        
        else:
             # Agent vs Agent / Agent vs User
             # We use the generic 30s wait if we want to poll.
             # But usually an Agent calls waitForNextTurn expecting to see the board.
             # If the board hasn't changed since last time... how do we know?
             # We don't.
             # So we assume the Agent is smart.
             # Actually, let's just return the state immediately always for non-computer (async/sync is up to agents).
             # UNLESS we want to support "Blocking for human move".
             # If showUi=True, likely waiting for Human.
             if game.config.get("showUi"):
                  # Waiting for UI interaction...
                  # We should BLOCK until UI posts a move?
                  # Yes, otherwise loop spins hot.
                  try:
                      await asyncio.wait_for(game.move_event.wait(), timeout=30.0)
                  except asyncio.TimeoutError:
                      # If existing state, maybe just return it with "Waiting for user..."?
                      # Spec says "Return Condition 2 (Timeout)... Timeout message".
                      return ["Timeout: No move received yet. Please call this tool again immediately."]
    
    except Exception as e:
        return [f"Error during wait: {str(e)}"]

    # Generate Content
    # 1. Markdown
    md = render_board_to_markdown(game.board.fen())
    
    content = []
    content.append(md)
    
    # 2. UI Resource
    if game.config.get("showUi"):
        html = render_board_to_html(game.board.fen(), game.id)
        # Construct UI Resource manually or via helper? 
        # FastMCP might not have a helper for EmbeddedResource yet (it's new).
        # We return a dict that conforms to the schema or simple text if not supported.
        # But FastMCP signature says -> list.
        # Let's try to return raw dict for resource.
        
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
async def finishTurn(game_id: str, move: str, claim_win: bool = False) -> str:
    """
    Submits a move to the game server.
    Arguments:
    - game_id: ID of the game
    - move: UCI format (e.g. e2e4)
    - claim_win: Set to true to claim checkmate/win.
    """
    try:
        result = await manager.make_move(game_id, move, claim_win)
        
        # Check game over after move
        game = manager.get_game(game_id)
        if game and game.is_game_over:
            return f"Move accepted. Game Over: {game.result}"
            
        return result
    except ValueError as e:
        return f"Error: {str(e)}"
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
