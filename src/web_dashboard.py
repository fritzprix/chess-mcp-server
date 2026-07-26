from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from pydantic import BaseModel
import uvicorn
import asyncio
import os
import re
import json
import importlib.metadata
import chess.pgn
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
        game.listeners.append(q)
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
            if q in game.listeners:
                game.listeners.remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/dashboard/events")
async def dashboard_events_sse(request: Request):
    """Server-Sent Events endpoint for real-time dashboard updates."""
    async def event_generator():
        q = asyncio.Queue()
        manager.dashboard_listeners.append(q)
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
            if q in manager.dashboard_listeners:
                manager.dashboard_listeners.remove(q)

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
    if game.result:
        pgn_game.headers["Result"] = game.result

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

def get_active_port():
    return ACTIVE_PORT

def find_available_port(start_port=8080, max_attempts=20):
    import socket
    for p in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return start_port

def start_dashboard(port=8080):
    global ACTIVE_PORT
    ACTIVE_PORT = find_available_port(port)
    uvicorn.run(app, host="0.0.0.0", port=ACTIVE_PORT, log_level="error")

