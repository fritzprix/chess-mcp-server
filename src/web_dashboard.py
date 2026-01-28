from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
import asyncio
from typing import List
from src.game_state import GameManager
from src.rendering import render_board_to_html

app = FastAPI(title="Chess MCP Dashboard")
manager = GameManager()


import os
import re
import importlib.metadata

def get_version():
    # First try to get the version from the installed package
    try:
        return importlib.metadata.version("chess-mcp-server")
    except importlib.metadata.PackageNotFoundError:
        pass

    # Fallback to reading pyproject.toml for local development
    try:
        # Assuming pyproject.toml is in the root, one level up from src
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
    
    # Setup Jinja2
    current_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(current_dir, "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("dashboard.html")
    
    html = template.render(
        games=games,
        version=version
    )
    
    return html

@app.get("/game/{game_id}", response_class=HTMLResponse)
async def view_game(game_id: str):
    game = manager.get_game(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
        
    # We reuse the render logic but disable interaction for spectator? 
    # Or keep it interactive but actions won't work if not via MCP?
    # Actually, the postMessage logic won't work in a normal browser (no parent).
    # So we should render a read-only version or one that logs to console.
    
    # For now, let's just reuse the HTML generator
    html = render_board_to_html(game.board.fen(), game.id)
    
    # Wrap in a back link
    wrapper = f"""
    <div><a href="/"><< Back to Dashboard</a></div>
    {html}
    """
    return wrapper

def start_dashboard(port=8080):
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="error")
