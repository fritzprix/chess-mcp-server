import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import chess


@dataclass(frozen=True)
class _TranspositionEntry:
    depth: int
    value: int
    flag: str
    best_move: Optional[chess.Move]


class ChessAI:
    """Small deterministic chess engine with configurable blunder rates."""

    def __init__(self):
        self.levels = {
            1: {"depth": 1, "error_rate": 0.60},
            2: {"depth": 1, "error_rate": 0.40},
            3: {"depth": 1, "error_rate": 0.20},
            4: {"depth": 2, "error_rate": 0.15},
            5: {"depth": 2, "error_rate": 0.10},
            6: {"depth": 3, "error_rate": 0.08},
            7: {"depth": 3, "error_rate": 0.04},
            8: {"depth": 3, "error_rate": 0.00},
            9: {"depth": 4, "error_rate": 0.00},
            10: {"depth": 4, "error_rate": 0.00},
        }
        self.piece_values = {
            chess.PAWN: 100,
            chess.KNIGHT: 320,
            chess.BISHOP: 330,
            chess.ROOK: 500,
            chess.QUEEN: 900,
            chess.KING: 0,
        }
        self._mate_score = 100_000
        self._quiescence_depth = 4
        self._transposition_table: Dict[Tuple[object, ...], _TranspositionEntry] = {}

    def get_move(self, board: chess.Board, level: int) -> Optional[chess.Move]:
        """Return the best legal move for the requested difficulty level."""
        settings = self.levels.get(level, self.levels[5])
        legal_moves = list(board.legal_moves)
        if not legal_moves or self._terminal_score(board, 0) is not None:
            return None

        if random.random() < settings["error_rate"]:
            return random.choice(legal_moves)

        self._transposition_table.clear()
        return self._get_best_move_minimax(board, settings["depth"])

    @staticmethod
    def _lone_king_loser(board: chess.Board) -> Optional[chess.Color]:
        white_pieces = [
            piece for piece in board.piece_map().values() if piece.color == chess.WHITE
        ]
        black_pieces = [
            piece for piece in board.piece_map().values() if piece.color == chess.BLACK
        ]
        if len(white_pieces) == 1 and len(black_pieces) > 1:
            return chess.WHITE
        if len(black_pieces) == 1 and len(white_pieces) > 1:
            return chess.BLACK
        return None

    def _terminal_score(self, board: chess.Board, ply: int) -> Optional[int]:
        lone_king_loser = self._lone_king_loser(board)
        if lone_king_loser == chess.WHITE:
            return -self._mate_score + ply
        if lone_king_loser == chess.BLACK:
            return self._mate_score - ply
        if board.is_checkmate():
            return (
                -self._mate_score + ply
                if board.turn == chess.WHITE
                else self._mate_score - ply
            )
        if board.is_game_over():
            return 0
        return None

    def _evaluate_board(self, board: chess.Board, ply: int = 0) -> int:
        terminal_score = self._terminal_score(board, ply)
        if terminal_score is not None:
            return terminal_score

        score = 0
        for square, piece in board.piece_map().items():
            value = self.piece_values[piece.piece_type]
            file_distance = abs(3.5 - chess.square_file(square))
            rank = chess.square_rank(square)
            relative_rank = rank if piece.color == chess.WHITE else 7 - rank
            center_bonus = max(0, int(4 - file_distance - abs(3.5 - rank)))
            advancement_bonus = relative_rank * 4 if piece.piece_type == chess.PAWN else 0
            positional_bonus = center_bonus * (
                5 if piece.piece_type in (chess.KNIGHT, chess.BISHOP) else 2
            )
            piece_score = value + positional_bonus + advancement_bonus
            score += piece_score if piece.color == chess.WHITE else -piece_score

        mobility = board.legal_moves.count()
        opponent = board.copy(stack=False)
        opponent.push(chess.Move.null())
        opponent_mobility = opponent.legal_moves.count()
        score += 2 * (mobility - opponent_mobility)
        return score

    @staticmethod
    def _position_key(board: chess.Board) -> Tuple[object, ...]:
        return (
            board.board_fen(),
            board.turn,
            board.castling_rights,
            board.ep_square,
        )

    def _move_order_score(self, board: chess.Board, move: chess.Move) -> int:
        score = 0
        if board.is_capture(move):
            captured = board.piece_at(move.to_square)
            captured_value = self.piece_values[captured.piece_type] if captured else 100
            moving_piece = board.piece_at(move.from_square)
            moving_value = self.piece_values[moving_piece.piece_type] if moving_piece else 0
            score += 10_000 + captured_value * 10 - moving_value
        if move.promotion:
            score += 9_000 + self.piece_values.get(move.promotion, 0)
        if board.gives_check(move):
            score += 5_000
        return score

    def _order_moves(
        self,
        board: chess.Board,
        moves: List[chess.Move],
        preferred_move: Optional[chess.Move] = None,
    ) -> List[chess.Move]:
        return sorted(
            moves,
            key=lambda move: (
                move == preferred_move,
                self._move_order_score(board, move),
            ),
            reverse=True,
        )

    def _quiescence(
        self,
        board: chess.Board,
        alpha: float,
        beta: float,
        maximizing: bool,
        ply: int,
        depth: int,
    ) -> int:
        terminal_score = self._terminal_score(board, ply)
        if terminal_score is not None:
            return terminal_score
        stand_pat = self._evaluate_board(board, ply)
        if depth == 0:
            return stand_pat

        if maximizing:
            if stand_pat >= beta:
                return stand_pat
            alpha = max(alpha, stand_pat)
        else:
            if stand_pat <= alpha:
                return stand_pat
            beta = min(beta, stand_pat)

        tactical_moves = [
            move for move in board.legal_moves
            if board.is_check() or board.is_capture(move) or board.gives_check(move)
        ]
        for move in self._order_moves(board, tactical_moves):
            board.push(move)
            value = self._quiescence(
                board,
                alpha,
                beta,
                board.turn == chess.WHITE,
                ply + 1,
                depth - 1,
            )
            board.pop()
            if maximizing:
                stand_pat = max(stand_pat, value)
                alpha = max(alpha, stand_pat)
            else:
                stand_pat = min(stand_pat, value)
                beta = min(beta, stand_pat)
            if beta <= alpha:
                break
        return int(stand_pat)

    def _minimax(
        self,
        board: chess.Board,
        depth: int,
        alpha: float,
        beta: float,
        maximizing: bool,
        ply: int = 0,
    ) -> int:
        terminal_score = self._terminal_score(board, ply)
        if terminal_score is not None:
            return terminal_score
        if depth <= 0:
            return self._quiescence(
                board, alpha, beta, maximizing, ply, self._quiescence_depth
            )

        original_alpha = alpha
        original_beta = beta
        key = self._position_key(board)
        cached = self._transposition_table.get(key)
        preferred_move = cached.best_move if cached else None
        if cached and cached.depth >= depth:
            if cached.flag == "exact":
                return cached.value
            if cached.flag == "lower":
                alpha = max(alpha, cached.value)
            elif cached.flag == "upper":
                beta = min(beta, cached.value)
            if alpha >= beta:
                return cached.value

        legal_moves = self._order_moves(board, list(board.legal_moves), preferred_move)
        if not legal_moves:
            return self._evaluate_board(board, ply)

        best_move = legal_moves[0]
        if maximizing:
            value = -math.inf
            for move in legal_moves:
                board.push(move)
                child_value = self._minimax(
                    board, depth - 1, alpha, beta, board.turn == chess.WHITE, ply + 1
                )
                board.pop()
                if child_value > value:
                    value, best_move = child_value, move
                alpha = max(alpha, value)
                if beta <= alpha:
                    break
        else:
            value = math.inf
            for move in legal_moves:
                board.push(move)
                child_value = self._minimax(
                    board, depth - 1, alpha, beta, board.turn == chess.WHITE, ply + 1
                )
                board.pop()
                if child_value < value:
                    value, best_move = child_value, move
                beta = min(beta, value)
                if beta <= alpha:
                    break

        result = int(value)
        if result <= original_alpha:
            flag = "upper"
        elif result >= original_beta:
            flag = "lower"
        else:
            flag = "exact"
        self._transposition_table[key] = _TranspositionEntry(
            depth, result, flag, best_move
        )
        return result

    def _get_best_move_minimax(
        self,
        board: chess.Board,
        depth: int,
    ) -> Optional[chess.Move]:
        legal_moves = self._order_moves(board, list(board.legal_moves))
        if not legal_moves:
            return None

        maximizing = board.turn == chess.WHITE
        best_move = legal_moves[0]
        best_value = -math.inf if maximizing else math.inf
        alpha = -math.inf
        beta = math.inf

        for move in legal_moves:
            board.push(move)
            value = self._minimax(
                board, depth - 1, alpha, beta, board.turn == chess.WHITE, ply=1
            )
            board.pop()
            if (maximizing and value > best_value) or (not maximizing and value < best_value):
                best_value, best_move = value, move
            if maximizing:
                alpha = max(alpha, best_value)
            else:
                beta = min(beta, best_value)
        return best_move
