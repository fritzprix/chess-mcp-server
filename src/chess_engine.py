import chess
import math
import random

class ChessAI:
    def __init__(self):
        # Configuration for 10 levels
        self.levels = {
            1:  {"depth": 1, "error_rate": 0.60},
            2:  {"depth": 1, "error_rate": 0.40},
            3:  {"depth": 1, "error_rate": 0.20},
            4:  {"depth": 2, "error_rate": 0.20},
            5:  {"depth": 2, "error_rate": 0.10},
            6:  {"depth": 3, "error_rate": 0.10},
            7:  {"depth": 3, "error_rate": 0.05},
            8:  {"depth": 3, "error_rate": 0.00},
            9:  {"depth": 4, "error_rate": 0.05},
            10: {"depth": 4, "error_rate": 0.00},
        }
        
        # Piece values for evaluation
        # Simple material evaluation
        self.piece_values = {
            chess.PAWN: 10, chess.KNIGHT: 30, chess.BISHOP: 30,
            chess.ROOK: 50, chess.QUEEN: 90, chess.KING: 900
        }

    def get_move(self, board: chess.Board, level: int) -> chess.Move:
        """
        Returns the best move based on the difficulty level (1-10).
        """
        if level not in self.levels:
            level = 5 # Default to medium
            
        settings = self.levels[level]
        depth = settings["depth"]
        error_rate = settings["error_rate"]

        # 1. Error Chance (Simulate Blunder)
        # If the random roll is within the error rate, pick a random legal move.
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return None # No moves available (Checkmate/Stalemate)

        if random.random() < error_rate:
            return random.choice(legal_moves)

        # 2. Strategic Calculation (Minimax)
        # Otherwise, calculate the best move using Minimax.
        return self._get_best_move_minimax(board, depth)

    def _evaluate_board(self, board):
        if board.is_checkmate():
            return -9999 if board.turn else 9999
        if board.is_stalemate() or board.is_insufficient_material():
            return 0

        score = 0
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece:
                value = self.piece_values[piece.piece_type]
                if piece.color == chess.WHITE:
                    score += value
                else:
                    score -= value
        return score

    def _minimax(self, board, depth, alpha, beta, maximizing):
        if depth == 0 or board.is_game_over():
            return self._evaluate_board(board)

        legal_moves = list(board.legal_moves)
        
        if maximizing:
            max_eval = -math.inf
            for move in legal_moves:
                board.push(move)
                eval = self._minimax(board, depth - 1, alpha, beta, False)
                board.pop()
                max_eval = max(max_eval, eval)
                alpha = max(alpha, eval)
                if beta <= alpha:
                    break
            return max_eval
        else:
            min_eval = math.inf
            for move in legal_moves:
                board.push(move)
                eval = self._minimax(board, depth - 1, alpha, beta, True)
                board.pop()
                min_eval = min(min_eval, eval)
                beta = min(beta, eval)
                if beta <= alpha:
                    break
            return min_eval

    def _get_best_move_minimax(self, board, depth):
        best_move = None
        best_value = -math.inf if board.turn == chess.WHITE else math.inf
        alpha = -math.inf
        beta = math.inf
        
        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return None
        
        # Simple optimization: shuffle moves to prevent deterministic behavior on equal scores
        random.shuffle(legal_moves)

        for move in legal_moves:
            board.push(move)
            # Pass opposite of current turn because we just pushed a move and now it's opponent's turn to minimize/maximize
            value = self._minimax(board, depth - 1, alpha, beta, not board.turn)
            board.pop()

            if board.turn == chess.WHITE:
                if value > best_value:
                    best_value = value
                    best_move = move
                alpha = max(alpha, best_value)
            else:
                if value < best_value:
                    best_value = value
                    best_move = move
                beta = min(beta, best_value)
                
        # Fallback if no best move found (should rely on random legal or standard)
        if best_move is None and legal_moves:
            return random.choice(legal_moves)
            
        return best_move
