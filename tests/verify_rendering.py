import sys
import os

# Ensure project root is in path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.rendering import render_board_to_markdown
import chess

def verify_rendering():
    # Standard starting position
    fen = chess.STARTING_FEN
    
    # Test with player color
    output = render_board_to_markdown(fen, player_color="White")
    
    print("--- Rendered Output ---")
    print(output)
    print("-----------------------")
    
    # Check for presence of letters
    if "P" in output and "p" in output and "N" in output:
        print("SUCCESS: Found algebraic notation (letters).")
    else:
        print("FAILURE: Did not find expected algebraic notation.")
        
    # Check for absence of emojis (checking a few common ones)
    emojis = ["♙", "♘", "♗", "♖", "♕", "♔"]
    found_emoji = False
    for e in emojis:
        if e in output:
            found_emoji = True
            print(f"FAILURE: Found emoji {e}")
            break
            
    if not found_emoji:
        print("SUCCESS: No emojis found.")

    # Check for Legend
    if "Legend" in output:
        print("SUCCESS: Legend found.")
    else:
        print("FAILURE: Legend not found.")
        
    # Check for Player Color
    if "You are playing: White" in output:
        print("SUCCESS: Player color found.")
    else:
        print("FAILURE: Player color not found.")

if __name__ == "__main__":
    verify_rendering()
