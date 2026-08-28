import asyncio
import threading
import chess
from typing import Literal
from mcp.server.fastmcp import FastMCP
import mcp.types as types
from pydantic import Field

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
from src.web_dashboard import start_dashboard, get_active_port, get_dashboard_url


# Initialize FastMCP
mcp = FastMCP("Chess Server")
manager = GameManager()
DASHBOARD_PORT = 8080

# --- Tools ---

def _embed_board_ui(
    game,
    ui_color: str,
    player_token: str | None = None,
) -> types.EmbeddedResource:
    is_white_perspective = (ui_color == "white")
    difficulty = game.config.get("difficulty", 5)
    game_type = game.config.get("type", "computer")
    html = render_board_to_html(
        game.board.fen(),
        game.id,
        is_white_perspective=is_white_perspective,
        difficulty=difficulty,
        game_type=game_type,
        player_token=player_token,
    )
    return types.EmbeddedResource(
        type="resource",
        resource=types.TextResourceContents(
            uri=f"ui://chess/{game.id}",
            mimeType="text/html",
            text=html,
        ),
    )


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
    showUi = (type == "human")

    config = {
        "type": type,
        "color": color,
        "showUi": showUi,
        "difficulty": difficulty
    }
    game = manager.create_game(config)
    opponent_color = "black" if color == "white" else "white"
    browser_token = (
        game.black_token if opponent_color == "black" else game.white_token
    )
    game_url = f"{get_dashboard_url()}/game/{game.id}"
    if browser_token:
        game_url += f"?player_token={browser_token}"
    _schedule_open_game_in_browser(game_url)

    content = []

    base_info = (
        f"Game Created Successfully!\n"
        f"- Game ID: {game.id}\n"
        f"- Type: {type}\n"
        f"- You are: {color.title()}\n"
        f"- Player token: {game.player_token}\n"
        f"- Difficulty: Level {difficulty} (if computer)\n"
        f"- Board: {game_url}\n"
        f"- Dashboard: {get_dashboard_url()}\n"
    )

    if color == "white":
        my_color_str = "White"
        md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
        md += (
            f"\n\n🎯 **REQUIRED NEXT ACTION**: Game started! You are White and move first. "
            f"Review the board state above, select your move, and call "
            f"`finishTurn(game_id='{game.id}', move='<your_move>', player_token='{game.player_token}')` immediately."
        )

        full_text = base_info + "\n" + md
        content.append(types.TextContent(type="text", text=full_text))

        if showUi:
            ui_token = game.black_token if color == "white" else game.white_token
            content.append(_embed_board_ui(game, opponent_color, ui_token))

    else:
        first_move_msg = ""
        if type == "computer":
            first_move_msg = " Computer (White) is calculating its first move..."

            full_text = (
                base_info
                + f"\n{first_move_msg}\n\n⏳ **REQUIRED NEXT ACTION**: Game started! You are Black. "
                f"Computer moves first. Call `waitForNextTurn(game_id='{game.id}', player_token='{game.player_token}')` immediately "
                f"to receive the computer's move."
            )
            content.append(types.TextContent(type="text", text=full_text))
        else:
            full_text = (
                base_info
                + f"\n\n⏳ **REQUIRED NEXT ACTION**: Game started! You are Black. Opponent (White) moves first. "
                f"Call `waitForNextTurn(game_id='{game.id}', player_token='{game.player_token}')` immediately to wait for the opponent's move."
            )
            content.append(types.TextContent(type="text", text=full_text))

            if showUi:
                ui_token = game.white_token if color == "black" else game.black_token
                content.append(_embed_board_ui(game, opponent_color, ui_token))

    return content


@mcp.tool()
async def waitForNextTurn(
    game_id: str = Field(..., description="The ID of the active game."),
    player_token: str | None = Field(None, description="The player token returned by createGame or joinGame.")
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

        my_color = manager.get_player_color(game_id, player_token)
        status = await manager.wait_until_turn(game, my_color, timeout=30.0)

        if status == "timeout":
            return [types.TextContent(
                type="text",
                text=(
                    f"⏳ Timeout: No move received from opponent within 30s.\n\n"
                    f"👉 **REQUIRED NEXT ACTION**: Call `waitForNextTurn(game_id='{game.id}', player_token='{player_token}')` "
                    f"again immediately to continue waiting."
                ),
            )]

        if status == "game_not_found":
            raise ValueError(f"Game '{game_id}' was deleted while waiting.")

        if status == "game_over" or game.is_game_over:
            return [types.TextContent(type="text", text=f"🏆 Game Over: {game.result}. The game has concluded!")]

    except Exception as e:
        raise RuntimeError(
            f"Error while waiting for turn in game '{game_id}': {str(e)}\n\n"
            f"👉 **REQUIRED NEXT ACTION**: Call `waitForNextTurn(game_id='{game_id}', player_token='{player_token}')` again to retry waiting."
        )

    my_color_str = "White" if my_color == chess.WHITE else "Black"
    md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)

    md += (
        f"\n\n🎯 **REQUIRED NEXT ACTION**: Opponent has moved! It is now your turn ({my_color_str}). "
        f"Review the board state above, select your move in UCI format (e.g. 'e2e4'), and call "
        f"`finishTurn(game_id='{game.id}', move='<your_move>', player_token='{player_token}')` immediately."
    )

    content = [types.TextContent(type="text", text=md)]

    if game.config.get("showUi"):
        agent_color = "white" if my_color == chess.WHITE else "black"
        content.append(_embed_board_ui(game, agent_color, player_token))

    return content


@mcp.tool()
async def finishTurn(
    game_id: str = Field(..., description="The ID of the active game."),
    move: str = Field(..., description="The move in UCI format (e.g., 'e2e4')."),
    claim_win: bool = Field(False, description="Set to true if you are claiming Checkmate or Win with this move."),
    player_token: str | None = Field(None, description="The player token returned by createGame or joinGame.")
) -> list:
    """
    Submits a move to the game server.
    """
    try:
        await manager.make_move(game_id, move, claim_win, player_token)
        game = manager.get_game(game_id)
        if not game:
            raise ValueError(f"Game '{game_id}' not found after move.")

        agent_color = manager.get_player_color(game_id, player_token)
        is_agent_turn = (game.board.turn == agent_color)

        content = []

        if game.is_game_over:
            msg = f"🏆 Move accepted. Game Over: {game.result}. The game has concluded! No further actions needed."
            content.append(types.TextContent(type="text", text=msg))
            return content

        msg = f"✅ Move '{move}' accepted."

        if is_agent_turn:
            msg += "\nIt is now your turn again."
            content.append(types.TextContent(type="text", text=msg))

            my_color_str = "White" if agent_color == chess.WHITE else "Black"
            md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)
            md += (
                f"\n\n🎯 **REQUIRED NEXT ACTION**: Review the board state above, select your next move "
                f"in UCI format (e.g. 'e2e4'), and call `finishTurn(game_id='{game.id}', move='<your_move>', player_token='{player_token}')` immediately."
            )
            content.append(types.TextContent(type="text", text=md))
        else:
            msg += (
                f"\n\n⏳ **REQUIRED NEXT ACTION**: Your move is complete. Opponent is thinking. "
                f"Call `waitForNextTurn(game_id='{game.id}', player_token='{player_token}')` immediately to wait for the opponent's move."
            )
            content.append(types.TextContent(type="text", text=msg))

            if game.config.get("showUi"):
                agent_color = game.config.get("color", "white")
                ui_color = "black" if agent_color == "white" else "white"
                ui_token = game.black_token if ui_color == "black" else game.white_token
                content.append(_embed_board_ui(game, ui_color, ui_token))

        return content

    except ValueError as e:
        game = manager.get_game(game_id)
        board_hint = ""
        if game:
            my_color_str = game.config.get("color", "white").title()
            board_hint = "\n\n" + render_board_to_markdown(game.board.fen(), player_color=my_color_str)
        raise ValueError(
            f"❌ Move Failed: '{move}' is invalid or illegal.\n"
            f"Details: {str(e)}"
            f"{board_hint}\n\n"
            f"👉 **REQUIRED NEXT ACTION**: Review the error details and board state above, select a valid "
            f"legal move in UCI format (e.g. 'e2e4'), and call "
            f"`finishTurn(game_id='{game_id}', move='<your_move>', player_token='{player_token}')` again immediately to retry!"
        )
    except Exception as e:
        raise RuntimeError(
            f"❌ Error submitting move '{move}': {str(e)}\n\n"
            f"👉 **REQUIRED NEXT ACTION**: Check the game state and call "
            f"`finishTurn(game_id='{game_id}', move='<your_move>', player_token='{player_token}')` again to retry."
        )


@mcp.tool()
def joinGame(
    game_id: str = Field(..., description="The ID of the game to join.")
) -> list:
    """
    Joins an existing chess game.
    Returns the current board state and turn information.
    """
    try:
        game, player_token, joined_color = manager.join_game(game_id)
    except ValueError as error:
        raise ValueError(
            f"Unable to join game '{game_id}': {error}"
        ) from error

    content = []
    msg = f"Joined Game '{game.id}' Successfully.\n"
    my_color_str = "White" if joined_color == chess.WHITE else "Black"
    msg += f"You are: {my_color_str}.\n"
    msg += f"Player token: {player_token}\n"
    turn_color = "White" if game.board.turn == chess.WHITE else "Black"
    msg += f"Current Turn: {turn_color}.\n"

    md = render_board_to_markdown(game.board.fen(), player_color=my_color_str)

    msg += "\n" + md

    is_my_turn = (game.board.turn == joined_color)

    if is_my_turn:
        msg += (
            f"\n\n🎯 **REQUIRED NEXT ACTION**: It is YOUR turn! Review the board state above, decide your move "
            f"in UCI format (e.g. 'e2e4'), and call `finishTurn(game_id='{game.id}', move='<your_move>', player_token='{player_token}')` immediately."
        )
    else:
        msg += (
            f"\n\n⏳ **REQUIRED NEXT ACTION**: It is opponent's turn. "
            f"Call `waitForNextTurn(game_id='{game.id}', player_token='{player_token}')` immediately to wait for their move."
        )

    content.append(types.TextContent(type="text", text=msg))
    return content


# --- Entry Point ---

def _schedule_open_game_in_browser(url: str) -> None:
    """Open a game board URL in the background without blocking MCP stdio."""
    threading.Thread(
        target=open_browser_stdio_safe,
        args=(url,),
        daemon=True,
    ).start()


def open_browser_stdio_safe(url: str) -> None:
    """
    Open a URL in the user's browser without inheriting MCP stdio pipes.

    On Linux, Chrome prints status text like
    "기존 브라우저 세션에서 여는 중입니다." to the inherited stdout fd.
    That corrupts the MCP JSON-RPC stream when transport=stdio.
    Always spawn with stdout/stderr redirected to DEVNULL.
    """
    import shutil
    import subprocess

    candidates: list[list[str]] = []
    browser_env = os.environ.get("BROWSER")
    if browser_env:
        # BROWSER may be "firefox %s" or a bare path.
        if "%s" in browser_env:
            candidates.append(browser_env.replace("%s", url).split())
        else:
            candidates.append([browser_env, url])

    for opener in ("xdg-open", "gio", "gnome-open", "open"):
        path = shutil.which(opener)
        if not path:
            continue
        if opener == "gio":
            candidates.append([path, "open", url])
        else:
            candidates.append([path, url])

    for cmd in candidates:
        try:
            subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            return
        except OSError:
            continue

    # Last resort: webbrowser may still inherit fds on some platforms.
    # Prefer failing silently over corrupting stdio.
    print(
        f"Dashboard ready but could not auto-open browser. Open manually: {url}",
        file=sys.stderr,
    )


def launch_dashboard_thread():
    """
    Run the HTTP dashboard in a supervised loop on a background thread.

    Must never block the MCP stdio main thread — any wait before mcp.run()
    starves the initialize handshake ("connection closed: initialize response").
    """
    from src.web_dashboard import (
        get_active_port,
        get_dashboard_error,
        wait_for_dashboard,
    )
    import time

    ready_notifier = threading.Thread(
        target=_announce_dashboard_when_ready,
        args=(wait_for_dashboard, get_active_port, get_dashboard_error),
        daemon=True,
    )
    ready_notifier.start()

    while True:
        try:
            start_dashboard(port=DASHBOARD_PORT)
            print(
                "Dashboard stopped unexpectedly; restarting in 1s...",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"Dashboard server thread exception: {e}", file=sys.stderr)
        time.sleep(1.0)


def _announce_dashboard_when_ready(wait_fn, get_port_fn, get_error_fn):
    """Announce dashboard URL on stderr and open browser without touching stdout."""
    if wait_fn(timeout=15.0):
        url = f"http://127.0.0.1:{get_port_fn()}"
        print(f"Chess MCP Dashboard ready at {url}", file=sys.stderr)
        threading.Thread(
            target=open_browser_stdio_safe,
            args=(url,),
            daemon=True,
        ).start()
    else:
        print(
            f"Chess MCP Server running, but dashboard failed to start on port "
            f"{DASHBOARD_PORT}+: {get_error_fn()}",
            file=sys.stderr,
        )


def main():
    """
    Main entry point for the Chess MCP Server.

    Critical: mcp.run(stdio) must start immediately. Any blocking work before
    it (dashboard wait, port probe, etc.) causes clients to see
    "connection closed: initialize response".
    """
    t = threading.Thread(target=launch_dashboard_thread, daemon=True)
    t.start()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
