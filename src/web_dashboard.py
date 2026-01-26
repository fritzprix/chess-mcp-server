from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn
import asyncio
from typing import List
from .game_state import GameManager
from .rendering import render_board_to_html

app = FastAPI(title="Chess MCP Dashboard")
manager = GameManager()

@app.get("/", response_class=HTMLResponse)
async def index():
    games = manager.list_games()
    
    rows = ""
    for g in games:
        rows += f"""
        <tr>
            <td><a href="/game/{g['id']}">{g['id']}</a></td>
            <td>{g['type']}</td>
            <td>{g['turn']}</td>
            <td>{g['fen']}</td>
            <td><button class="copy-btn" onclick="copyJoin('{g['id']}')">Copy Join Prompt</button></td>
        </tr>
        """
    
    html = f"""
    <html>
    <head><title>Chess MCP Dashboard</title>
    <style>
        table {{ width: 100%; border-collapse: collapse; }} 
        th, td {{ border: 1px solid #ddd; padding: 8px; }} 
        tr:nth-child(even){{background-color: #f2f2f2;}}
        .copy-btn {{ cursor: pointer; background: #007bff; color: white; border: none; padding: 5px 10px; border-radius: 3px; }}
        .copy-btn:hover {{ background: #0056b3; }}
    </style>
    <script>
        function copyJoin(gameId) {{
            const text = "Please join game " + gameId;
            navigator.clipboard.writeText(text).then(() => {{
                alert("Copied to clipboard: " + text);
            }}).catch(err => {{
                console.error('Failed to copy: ', err);
                prompt("Copy this text:", text);
            }});
        }}
    </script>
    </head>
    <body>
    <h1>Active Chess Games</h1>
    <table>
        <tr><th>ID</th><th>Type</th><th>Turn</th><th>FEN</th><th>Action</th></tr>
        {rows}
    </table>
    <br><a href="/" style="background:#eee; padding:5px;">Refresh</a>
    </body>
    </html>
    """
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
