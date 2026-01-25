import asyncio
import uuid
import chess
from typing import Dict, Optional
from dataclasses import dataclass, field
from .chess_engine import ChessAI

@dataclass
class GameInstance:
    id: str
    board: chess.Board
    config: dict
    # Event to notify when a move is made (wakes up waitForNextTurn)
    move_event: asyncio.Event = field(default_factory=asyncio.Event)
    
    # AI Engine if playing vs Computer
    ai: Optional[ChessAI] = None
    
    @property
    def is_game_over(self):
        return self.board.is_game_over()
    
    @property
    def result(self):
        if not self.is_game_over:
            return None
        outcome = self.board.outcome()
        if outcome.winner == chess.WHITE:
            return "White wins"
        elif outcome.winner == chess.BLACK:
            return "Black wins"
        else:
            return "Draw"

class GameManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GameManager, cls).__new__(cls)
            cls._instance.games: Dict[str, GameInstance] = {}
        return cls._instance

    def create_game(self, config: dict) -> GameInstance:
        game_id = str(uuid.uuid4())[:8]
        board = chess.Board()
        
        ai = None
        if config.get("type") == "computer":
            ai = ChessAI()
            
        game = GameInstance(
            id=game_id,
            board=board,
            config=config,
            ai=ai
        )
        self.games[game_id] = game
        return game

    def get_game(self, game_id: str) -> Optional[GameInstance]:
        return self.games.get(game_id)
        
    def list_games(self):
        return [
            {
                "id": g.id, 
                "fen": g.board.fen(), 
                "type": g.config.get("type"),
                "turn": "White" if g.board.turn == chess.WHITE else "Black"
            } 
            for g in self.games.values()
        ]

    async def make_move(self, game_id: str, move_uci: str, claim_win: bool = False) -> str:
        """
        Executes a move. 
        Returns 'OK' or raises generic exceptions.
        Triggers computer move if applicable.
        """
        game = self.get_game(game_id)
        if not game:
            raise ValueError(f"Game {game_id} not found")
        
        # Parse Move
        try:
            move = chess.Move.from_uci(move_uci)
        except ValueError:
            raise ValueError(f"Invalid UCI move format: '{move_uci}'. Please use standard format like 'e2e4' (start_square+end_square).")
            
        if move not in game.board.legal_moves:
             # Create a helpful list of some legal moves
            sample_moves = ", ".join([str(m) for m in list(game.board.legal_moves)[:3]])
            raise ValueError(f"Illegal move: '{move_uci}'. Review the board state. Sample legal moves: {sample_moves}...")
            
        # Execute Move
        game.board.push(move)
        
        # Check Claim
        if claim_win:
            if not game.board.is_checkmate():
                 # Revert? No, usually valid move but false claim is just an error message, 
                 # but spec said "Error - Failed Claim: Move rejected". So we should revert.
                 game.board.pop()
                 raise ValueError("Move rejected: You claimed Checkmate, but this move does not result in Checkmate.")
        
        # Notify waiters (User or Agent waiting for this move)
        game.move_event.set()
        game.move_event.clear() # Reset for next turn
        
        # If vs Computer and it's Computer's turn now (and game not over)
        if game.config.get("type") == "computer" and not game.board.is_game_over():
            # Trigger Background AI Move
            # We use asyncio.create_task to run it without blocking the return of this function
            asyncio.create_task(self._computer_turn(game))
            
        return "Move accepted"

    async def _computer_turn(self, game: GameInstance):
        """
        Calculates and executes computer move.
        """
        # Simulate thinking time?
        await asyncio.sleep(0.5)
        
        difficulty = game.config.get("difficulty", 5)
        ai_move = game.ai.get_move(game.board, difficulty)
        
        if ai_move:
            game.board.push(ai_move)
            # Notify waiters (Agent waiting for computer)
            game.move_event.set()
            game.move_event.clear()
            
