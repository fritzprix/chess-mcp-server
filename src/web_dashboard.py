from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from pydantic import BaseModel
import uvicorn
import asyncio
import os
import re
import json
import sys
import importlib.metadata
import chess.pgn
import threading
from typing import List, Optional
from src.game_state import GameManager
from src.rendering import render_board_to_html

app = FastAPI(title="Chess MCP Dashboard")
manager = GameManager()

class MoveRequest(BaseModel):
    move: str
    claim_win: bool = False

def get_version():
    try:
        return importlib.metadata.version("chess-mcp-server")
    except importlib.metadata.PackageNotFoundError:
        pass

    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        pyproject_path = os.path.join(project_root, "pyproject.toml")
        
        with open(pyproject_path, "r", encoding="utf-8") as f:
            content = f.read()
            match = re.search(r'version\s*=\s*"(.*?)"', content)
            if match:
                return match.group(1)
    except Exception:
        pass
    return "Unknown"

@app.get("/", response_class=HTMLResponse)
async def index():
    games = manager.list_games()
    version = get_version()
    
    from jinja2 import Environment, FileSystemLoader
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(current_dir, "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("dashboard.html")
    
    html = template.render(
        games=games,
        version=version
    )
    
    return html

@app.get("/api/dashboard/games")
async def get_dashboard_games():
    return manager.list_games()

@app.post("/api/dashboard/clear")
async def clear_dashboard_games():
    manager.clear_games(clear_all=True)
    return {"status": "ok", "games": []}

@app.get("/game/{game_id}", response_class=HTMLResponse)
async def view_game(game_id: str):
    game = manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
        
    difficulty = game.config.get("difficulty", 5)
    game_type = game.config.get("type", "computer")
    html = render_board_to_html(game.board.fen(), game.id, is_white_perspective=True, difficulty=difficulty, game_type=game_type)
    return html

@app.get("/api/game/{game_id}/state")
async def get_game_state(game_id: str):
    game = manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    return game.get_full_state()

@app.post("/api/game/{game_id}/move")
async def make_game_move(game_id: str, req: MoveRequest):
    game = manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    try:
        result = await manager.make_move(game_id, req.move, req.claim_win)
        return {"status": "ok", "message": result, "state": game.get_full_state()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/game/{game_id}/events")
async def game_events_sse(game_id: str, request: Request):
    """Server-Sent Events endpoint for real-time game updates."""
    game = manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    async def event_generator():
        q = asyncio.Queue()
        loop = asyncio.get_running_loop()
        entry = (loop, q)
        game.listeners.append(entry)
        try:
            # Send initial state event
            initial_data = game.get_full_state()
            initial_data["event_type"] = "init"
            yield f"data: {json.dumps(initial_data)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Ping keepalive
                    yield ": ping\n\n"
        finally:
            if entry in game.listeners:
                game.listeners.remove(entry)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/dashboard/events")
async def dashboard_events_sse(request: Request):
    """Server-Sent Events endpoint for real-time dashboard updates."""
    async def event_generator():
        q = asyncio.Queue()
        loop = asyncio.get_running_loop()
        entry = (loop, q)
        manager.dashboard_listeners.append(entry)
        try:
            initial_data = {
                "event_type": "init",
                "games": manager.list_games()
            }
            yield f"data: {json.dumps(initial_data)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            if entry in manager.dashboard_listeners:
                manager.dashboard_listeners.remove(entry)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/game/{game_id}/pgn")
async def get_game_pgn(game_id: str):
    """Generates PGN text for game replay export."""
    game = manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    pgn_game = chess.pgn.Game()
    pgn_game.headers["Event"] = f"Chess MCP Game {game_id}"
    pgn_game.headers["Site"] = "Chess MCP Server"
    pgn_game.headers["White"] = "Player 1"
    pgn_game.headers["Black"] = "Player 2"
    pgn_game.headers["Result"] = game.pgn_result

    node = pgn_game
    temp_board = chess.Board()
    for move_info in game.move_history:
        move = chess.Move.from_uci(move_info["uci"])
        node = node.add_variation(move)
        temp_board.push(move)

    pgn_text = str(pgn_game)
    return Response(content=pgn_text, media_type="application/x-chess-pgn", headers={
        "Content-Disposition": f"attachment; filename=game_{game_id}.pgn"
    })

ACTIVE_PORT = 8080
_dashboard_ready = threading.Event()
_dashboard_error: Optional[BaseException] = None
_PORT_FILE = os.path.join(
    __import__("tempfile").gettempdir(), "chess_mcp_dashboard.port"
)


def get_active_port() -> int:
    return ACTIVE_PORT


def get_dashboard_url() -> str:
    return f"http://127.0.0.1:{ACTIVE_PORT}"


def wait_for_dashboard(timeout: float = 5.0) -> bool:
    """Block until the dashboard has bound and completed startup."""
    return _dashboard_ready.wait(timeout)


def get_dashboard_error() -> Optional[BaseException]:
    return _dashboard_error


def _port_is_free(port: int) -> bool:
    """Return True if nothing is actively accepting connections on port."""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return False
    except OSError:
        return True


def find_available_port(start_port: int = 8080, max_attempts: int = 20) -> int:
    for p in range(start_port, start_port + max_attempts):
        if _port_is_free(p):
            return p
    raise OSError(f"No free port in range {start_port}-{start_port + max_attempts - 1}")


def _write_port_file(port: int) -> None:
    try:
        with open(_PORT_FILE, "w", encoding="utf-8") as f:
            f.write(str(port))
    except OSError as e:
        print(f"Warning: could not write port file {_PORT_FILE}: {e}", file=sys.stderr)


@app.on_event("startup")
async def _on_dashboard_startup():
    _write_port_file(ACTIVE_PORT)
    _dashboard_ready.set()
    print(
        f"Dashboard listening on http://127.0.0.1:{ACTIVE_PORT}",
        file=sys.stderr,
    )


def start_dashboard(port: int = 8080):
    """
    Bind the dashboard in this thread with its own asyncio event loop.
    Must not share the MCP stdio event loop on the main thread.
    Tries port, port+1, ... on bind failure.
    """
    global ACTIVE_PORT, _dashboard_error
    _dashboard_ready.clear()
    _dashboard_error = None
    last_err: Optional[BaseException] = None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        for p in range(port, port + 20):
            if not _port_is_free(p):
                print(f"Dashboard: port {p} in use, trying next...", file=sys.stderr)
                continue

            ACTIVE_PORT = p
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=p,
                log_level="warning",
                access_log=False,
                loop="asyncio",
            )
            server = uvicorn.Server(config)
            server.install_signal_handlers = lambda: None

            print(f"Dashboard: binding 0.0.0.0:{p} ...", file=sys.stderr)
            try:
                loop.run_until_complete(server.serve())
                print(f"Dashboard: server on port {p} stopped", file=sys.stderr)
                _dashboard_ready.clear()
                return
            except SystemExit as e:
                last_err = e
                print(f"Dashboard: bind/exit on {p}: {e}", file=sys.stderr)
                _dashboard_ready.clear()
                continue
            except OSError as e:
                last_err = e
                print(f"Dashboard: OSError on {p}: {e}", file=sys.stderr)
                _dashboard_ready.clear()
                continue
            except Exception as e:
                last_err = e
                _dashboard_error = e
                _dashboard_ready.clear()
                print(f"Dashboard: exception on {p}: {e}", file=sys.stderr)
                raise
    finally:
        try:
            loop.close()
        except Exception:
            pass

    _dashboard_error = last_err or RuntimeError(f"No free port near {port}")
    raise RuntimeError(
        f"Dashboard failed to bind any port in {port}-{port + 19}: {_dashboard_error}"
    )

