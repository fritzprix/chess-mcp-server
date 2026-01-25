import chess

def render_board_to_markdown(fen: str) -> str:
    """
    Converts a FEN string into a Markdown formatted table representation of the board.
    
    Args:
        fen (str): The Forsyth-Edwards Notation string of the game state.
        
    Returns:
        str: A multi-line string containing the Markdown table.
    """
    board = chess.Board(fen)
    
    lines = []
    lines.append("| Rank | a | b | c | d | e | f | g | h |")
    lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
    
    # 8(rank 7) to 1(rank 0)
    for rank in range(7, -1, -1):
        row_content = f"| **{rank + 1}** |"
        for file in range(8):
            piece = board.piece_at(chess.square(file, rank))
            symbol = piece.unicode_symbol() if piece else " " 
            row_content += f" {symbol} |"
        lines.append(row_content)
    
    return "\n".join(lines)

def render_board_to_html(fen: str, game_id: str, is_white_perspective: bool = True) -> str:
    """
    Renders an interactive HTML chess board for MCP-UI.
    Includes 'postMessage' logic for finishTurn.
    """
    board = chess.Board(fen)
    
    # Simple CSS/JS Board
    # We will use chess.js and chessboard.js via CDN or a simple SVG approach?
    # For a self-contained "resource", using a library via CDN is standard for web views.
    # However, MCP UI in tools might be sandboxed without external network access depending on Host.
    # Safe approach: Pure HTML/CSS Grid + Vanilla JS Drag Drop (Complex) OR use library.
    # Let's use a robust library: Chessboard.js + Chess.js (CDN).
    # If offline is required (as per mcp_reference_en hints), we might need to inline or stick to simple clicks.
    
    # Let's implement a simple "Click to Move" table-based UI with JS, 
    # as it's dependency-free and follows the "Production-level... without internet connectivity" hint in reference.
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        body {{ font-family: sans-serif; display: flex; flex-direction: column; align-items: center; }}
        .board {{ display: grid; grid-template-columns: repeat(8, 40px); grid-template-rows: repeat(8, 40px); border: 2px solid #333; }}
        .square {{ width: 40px; height: 40px; display: flex; justify-content: center; align-items: center; font-size: 30px; cursor: pointer; }}
        .white {{ background-color: #f0d9b5; }}
        .black {{ background-color: #b58863; }}
        .selected {{ background-color: #7b61ff !important; }}
        .controls {{ margin-top: 10px; display: flex; flex-direction: column; gap: 5px; }}
        input, button {{ padding: 5px; }}
        #status {{ margin-top: 10px; font-weight: bold; }}
    </style>
    </head>
    <body>
        <h2>Game: {game_id}</h2>
        <div id="board" class="board"></div>
        
        <div class="controls">
            <div>
                <label>Move (UCI): <input type="text" id="uciInput" placeholder="e2e4"></label>
            </div>
            <div>
                <label><input type="checkbox" id="chkClaimWin"> Claim Checkmate/Win</label>
            </div>
            <button onclick="submitMove()">Submit Move</button>
        </div>
        <div id="status"></div>

    <script>
        const fen = "{fen}";
        const gameId = "{game_id}";
        const isWhitePerspective = {'true' if is_white_perspective else 'false'};
        
        // Simple FEN parser to render board
        function renderBoard() {{
            const boardEl = document.getElementById('board');
            boardEl.innerHTML = '';
            
            const rows = fen.split(' ')[0].split('/');
            
            for (let r = 0; r < 8; r++) {{
                let fileIdx = 0;
                // Parse rank string (e.g., "rnbqkbnr")
                const rankStr = rows[r];
                for (let i = 0; i < rankStr.length; i++) {{
                    const char = rankStr[i];
                    if (isNaN(char)) {{
                        // It's a piece
                        createSquare(r, fileIdx, char);
                        fileIdx++;
                    }} else {{
                        // It's a number (empty spaces)
                        const empties = parseInt(char);
                        for (let k = 0; k < empties; k++) {{
                            createSquare(r, fileIdx, null);
                            fileIdx++;
                        }}
                    }}
                }}
            }}
        }}
        
        // Helper to check capitalization
        function isUpper(str) {{ return str === str.toUpperCase(); }}
        
        const pieceMap = {{
            'r': '♜', 'n': '♞', 'b': '♝', 'q': '♛', 'k': '♚', 'p': '♟',
            'R': '♖', 'N': '♘', 'B': '♗', 'Q': '♕', 'K': '♔', 'P': '♙'
        }};

        let selectedSq = null;

        function createSquare(row, col, pieceChar) {{
            const div = document.createElement('div');
            // Determine color (even sum = light/white, odd sum = dark/black)
            const isLight = (row + col) % 2 === 0;
            div.className = 'square ' + (isLight ? 'white' : 'black');
            div.dataset.row = row;
            div.dataset.col = col;
            
            if (pieceChar) {{
                div.textContent = pieceMap[pieceChar] || pieceChar;
                // Basic coloring for symbols if needed, but unicode is B&W usually
            }}
            
            div.onclick = () => onSquareClick(row, col);
            document.getElementById('board').appendChild(div);
        }}

        function onSquareClick(row, col) {{
            const file = String.fromCharCode(97 + col);
            const rank = 8 - row;
            const coord = file + rank;
            
            if (!selectedSq) {{
                // Select From
                selectedSq = coord;
                document.getElementById('status').innerText = "Selected: " + coord;
            }} else {{
                // Select To
                const move = selectedSq + coord;
                document.getElementById('uciInput').value = move;
                selectedSq = null;
                document.getElementById('status').innerText = "Move setup: " + move;
            }}
        }}

        function submitMove() {{
            const move = document.getElementById('uciInput').value;
            if (!move) {{
                alert("Please enter or select a move");
                return;
            }}
            
            const claimWin = document.getElementById('chkClaimWin').checked;
            
            // Post Message to MCP Host
            window.parent.postMessage({{
                type: 'action',
                action: 'finishTurn',
                payload: {{
                    game_id: gameId,
                    move: move,
                    claim_win: claimWin
                }}
            }}, '*');
            
            document.getElementById('status').innerText = "Submitted: " + move + "...";
        }}

        renderBoard();
    </script>
    </body>
    </html>
    """
    return html
