import unittest
import asyncio
import chess
from src.game_state import GameManager
from src.chess_engine import ChessAI

class TestChessServer(unittest.TestCase):
    def setUp(self):
        # Reset Singleton for isolation
        GameManager._instance = None
        self.manager = GameManager()

    def test_create_game(self):
        config = {"type": "computer", "difficulty": 1}
        game = self.manager.create_game(config)
        self.assertIsNotNone(game.id)
        self.assertIsNotNone(game.ai)
        self.assertEqual(game.config["difficulty"], 1)

    def test_make_move_logic(self):
        config = {"type": "agent"}
        game = self.manager.create_game(config)
        
        # White moves e4
        asyncio.run(self.manager.make_move(game.id, "e2e4"))
        self.assertEqual(game.board.piece_at(chess.E4).symbol(), "P")
        self.assertEqual(game.board.turn, chess.BLACK)

    def test_invalid_move(self):
        config = {"type": "agent"}
        game = self.manager.create_game(config)
        
        with self.assertRaises(ValueError):
            asyncio.run(self.manager.make_move(game.id, "e2e5")) # Illegal pawn jump

    def test_checkmate_claim_invalid(self):
        config = {"type": "agent"}
        game = self.manager.create_game(config)
        
        # e2e4 not checkmate
        with self.assertRaisesRegex(ValueError, "Move rejected: You claimed Checkmate"):
             asyncio.run(self.manager.make_move(game.id, "e2e4", claim_win=True))

    def test_engine_level_1(self):
        ai = ChessAI()
        board = chess.Board()
        # Level 1 has high error rate (60%). 
        # Running multiple times to ensure it returns a valid move at least.
        move = ai.get_move(board, level=1)
        self.assertIn(move, board.legal_moves)
    
    def test_rendering_content(self):
        from src.rendering import render_board_to_markdown
        md = render_board_to_markdown(chess.Board().fen(), player_color="White")
        self.assertIn("**Turn**: White to move", md)
        self.assertIn("**FEN**:", md)
        self.assertIn("**You are playing**: White", md)
        self.assertIn("Legend", md)
        # Check for algebraic notation (Pawn 'P')
        self.assertIn(" P ", md)

    def test_actionable_error_format(self):
        config = {"type": "agent"}
        game = self.manager.create_game(config)
        
        # 1. Invalid Format
        with self.assertRaises(ValueError) as cm:
             asyncio.run(self.manager.make_move(game.id, "invalid_format"))
        self.assertIn("Please use standard format", str(cm.exception))
        
        # 2. Illegal Move Advice
        with self.assertRaises(ValueError) as cm:
             asyncio.run(self.manager.make_move(game.id, "e2e8")) # Impossible move
        self.assertIn("Sample legal moves:", str(cm.exception))

if __name__ == '__main__':
    unittest.main()
