import chess

def render_board_to_markdown(fen: str, player_color: str = None) -> str:
    """
    Converts a FEN string into a Markdown formatted table representation of the board.
    
    Args:
        fen (str): The Forsyth-Edwards Notation string of the game state.
        player_color (str, optional): The color the agent is playing (e.g. "White", "Black").
        
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
            # Use standard algebraic notation (P, n, k, etc.) instead of unicode symbols
            symbol = piece.symbol() if piece else " " 
            row_content += f" {symbol} |"
        lines.append(row_content)
    
    # 5. Join lines to form the final string
    output = "\n".join(lines)
    
    # 6. Append State Info
    turn_text = "White" if board.turn == chess.WHITE else "Black"
    output += f"\n\n**Turn**: {turn_text} to move"
    output += f"\n**FEN**: `{fen}`"
    
    if player_color:
        output += f"\n**You are playing**: {player_color}"
        
    output += "\n\n> **Legend**: Uppercase = White (P, N, B, R, Q, K), Lowercase = Black (p, n, b, r, q, k)"
    
    return output

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
    
    display_turn = "White" if board.turn == chess.WHITE else "Black"
    user_side = "White" if is_white_perspective else "Black"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        body {{ font-family: sans-serif; display: flex; flex-direction: column; align-items: center; background-color: #2c2c2c; color: #f0f0f0; }}
        h2 {{ margin-bottom: 5px; }}
        .info {{ margin-bottom: 15px; text-align: center; }}
        .board {{ display: grid; grid-template-columns: repeat(8, 45px); grid-template-rows: repeat(8, 45px); border: 5px solid #4a4a4a; }}
        .square {{ width: 45px; height: 45px; display: flex; justify-content: center; align-items: center; font-size: 35px; cursor: pointer; user-select: none; }}
        .white {{ background-color: #eeeed2; color: black; }}
        .black {{ background-color: #769656; color: black; }}
        .selected {{ background-color: #bbcb2b !important; }}
        .controls {{ margin-top: 20px; display: flex; flex-direction: column; gap: 10px; background: #3c3c3c; padding: 15px; border-radius: 8px; }}
        input, button {{ padding: 8px; border-radius: 4px; border: none; }}
        button {{ background-color: #769656; color: white; cursor: pointer; font-weight: bold; }}
        button:hover {{ background-color: #567636; }}
        #status {{ margin-top: 10px; font-weight: bold; color: #ffd700; height: 20px; }}
    </style>
    </head>
    <body>
        <h2>Chess MCP</h2>
        <div class="info">
            <div>Game ID: {game_id}</div>
            <div style="font-size: 1.1em; margin-top: 5px;">You are: <strong>{user_side}</strong></div>
            <div style="color: #aaa;">To Move: {display_turn}</div>
        </div>
        
        <div id="board" class="board"></div>
        
        <div class="controls">
            <div>
                <label>Move (UCI): <input type="text" id="uciInput" placeholder="e.g. e2e4"></label>
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
        
        function renderBoard() {{
            const boardEl = document.getElementById('board');
            boardEl.innerHTML = '';
            
            const rows = fen.split(' ')[0].split('/');
            
            // FEN rows are Rank 8 down to Rank 1
            // If White Perspective: Render Row 0 (Rank 8) to Row 7 (Rank 1)
            // If Black Perspective: Render Row 7 (Rank 1) to Row 0 (Rank 8) ? 
            // Actually, we just need to iterate the grid differently.
            
            // Let's create a 2D array first for easier manipulation
            let grid = [];
            for (let r = 0; r < 8; r++) {{
                let rowArr = [];
                const rankStr = rows[r];
                for (let i = 0; i < rankStr.length; i++) {{
                    const char = rankStr[i];
                    if (isNaN(char)) {{
                        rowArr.push(char);
                    }} else {{
                        const empties = parseInt(char);
                        for (let k = 0; k < empties; k++) {{
                            rowArr.push(null);
                        }}
                    }}
                }}
                grid.push(rowArr);
            }}
            
            // Render Loops
            // White: r=0 (Rank 8) -> r=7 (Rank 1). c=0 (File a) -> c=7 (File h)
            // Black: r=7 (Rank 1) -> r=0 (Rank 8). c=7 (File h) -> c=0 (File a)
            
            const startR = isWhitePerspective ? 0 : 7;
            const endR = isWhitePerspective ? 8 : -1;
            const stepR = isWhitePerspective ? 1 : -1;
            
            const startC = isWhitePerspective ? 0 : 7;
            const endC = isWhitePerspective ? 8 : -1;
            const stepC = isWhitePerspective ? 1 : -1;
            
            for (let r = startR; r !== endR; r += stepR) {{
                for (let c = startC; c !== endC; c += stepC) {{
                     createSquare(r, c, grid[r][c]);
                }}
            }}
        }}
        
        const pieceMap = {{
            'r': '♜', 'n': '♞', 'b': '♝', 'q': '♛', 'k': '♚', 'p': '♟',
            'R': '♖', 'N': '♘', 'B': '♗', 'Q': '♕', 'K': '♔', 'P': '♙'
        }};

        let selectedSq = null;

        function createSquare(row, col, pieceChar) {{
            const div = document.createElement('div');
            // Color logic: (row+col)%2==0 is Light.
            // But 'row' index from FEN (0=Rank8) matches standard odd/even check?
            // Rank 8 (index 0) + File a (index 0) = 0 -> Light. Correct (a8 is light).
            const isLight = (row + col) % 2 === 0;
            div.className = 'square ' + (isLight ? 'white' : 'black');
            
            // Store logical coordinates for click handling
            div.dataset.row = row;
            div.dataset.col = col;
            
            if (pieceChar) {{
                div.textContent = pieceMap[pieceChar] || pieceChar;
            }}
            
            div.onclick = () => onSquareClick(row, col, div);
            document.getElementById('board').appendChild(div);
        }}

        function onSquareClick(row, col, divElement) {{
            const file = String.fromCharCode(97 + col);
            const rank = 8 - row;
            const coord = file + rank;
            
            // Clear previous selection highlight
            document.querySelectorAll('.selected').forEach(el => el.classList.remove('selected'));
            
            if (!selectedSq) {{
                // Select From
                selectedSq = coord;
                divElement.classList.add('selected');
                document.getElementById('status').innerText = "Selected: " + coord;
            }} else {{
                // Select To
                const move = selectedSq + coord;
                document.getElementById('uciInput').value = move;
                selectedSq = null; // Reset selection
                 document.getElementById('status').innerText = "Ready to submit: " + move;
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
            // Disable button to prevent double submit
            document.querySelector('button').disabled = true;
        }}

        renderBoard();
    </script>
    </body>
    </html>
    """
    return html
