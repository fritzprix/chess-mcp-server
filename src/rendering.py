import chess
from typing import Optional

def render_board_to_markdown(
    fen: str,
    player_color: Optional[str] = None,
    difficulty: Optional[int] = None,
) -> str:
    """
    Converts a FEN string into a Markdown formatted table representation of the board.
    
    Args:
        fen (str): The Forsyth-Edwards Notation string of the game state.
        player_color (str, optional): The color the agent is playing (e.g. "White", "Black").
        difficulty (int, optional): AI difficulty level if playing vs computer.
        
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
            symbol = piece.symbol() if piece else " " 
            row_content += f" {symbol} |"
        lines.append(row_content)
    
    output = "\n".join(lines)
    
    turn_text = "White" if board.turn == chess.WHITE else "Black"
    output += f"\n\n**Turn**: {turn_text} to move"
    output += f"\n**FEN**: `{fen}`"
    
    if player_color:
        output += f"\n**You are playing**: {player_color}"

    if difficulty:
        output += f"\n**Computer Difficulty**: Level {difficulty}"
        
    output += "\n\n> **Legend**: Uppercase = White (P, N, B, R, Q, K), Lowercase = Black (p, n, b, r, q, k)"
    
    return output

def render_board_to_html(
    fen: str,
    game_id: str,
    is_white_perspective: bool = True,
    difficulty: int = 5,
    game_type: str = "computer",
    player_token: Optional[str] = None,
    initial_fen: Optional[str] = None,
) -> str:
    """
    Renders an interactive HTML chess board for MCP-UI.
    Includes 'postMessage' logic for finishTurn.
    """
    board = chess.Board(fen)
    display_turn = "White" if board.turn == chess.WHITE else "Black"
    user_side = "White" if is_white_perspective else "Black"
    
    from jinja2 import Environment, FileSystemLoader
    import os
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(current_dir, "templates")
    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template("board.html")
    
    html = template.render(
        fen=fen,
        game_id=game_id,
        is_white_perspective=is_white_perspective,
        display_turn=display_turn,
        user_side=user_side,
        difficulty=difficulty,
        game_type=game_type,
        player_token=player_token,
        initial_fen=initial_fen or fen,
    )
    
    return html
