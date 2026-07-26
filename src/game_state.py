import asyncio
import uuid
import chess
import threading
import json
import os
from typing import Dict, Optional, List
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
    ai_task: Optional[asyncio.Task] = None
    
    # History of moves for visual play trace & replay
    # List of dicts: {"move_number": int, "san": str, "uci": str, "fen": str, "turn": str, "captured": str}
    move_history: List[dict] = field(default_factory=list)
    
    # Subscribers for SSE real-time updates
    listeners: List[asyncio.Queue] = field(default_factory=list)

    @property
    def is_game_over(self):
        return self.board.is_game_over()
    
    @property
    def result(self):
        if not self.is_game_over:
            return None
        outcome = self.board.outcome()
        if outcome is None:
            return None
        if outcome.winner == chess.WHITE:
            return "White wins"
        elif outcome.winner == chess.BLACK:
            return "Black wins"
        else:
            return "Draw"

    def notify_listeners(self, event_type: str = "update"):
        """Pushes state updates to all active SSE listener queues."""
        data = self.get_full_state()
        data["event_type"] = event_type
        
        # Remove dead queues or push event
        to_remove = []
        for q in self.listeners:
            try:
                q.put_nowait(data)
            except Exception:
                to_remove.append(q)
        for q in to_remove:
            if q in self.listeners:
                self.listeners.remove(q)

    def get_full_state(self) -> dict:
        """Returns comprehensive game state dictionary."""
        turn_str = "White" if self.board.turn == chess.WHITE else "Black"
        last_move = self.move_history[-1] if self.move_history else None
        
        # Captured pieces calculation
        captured_white = [] # White pieces captured by Black
        captured_black = [] # Black pieces captured by White
        
        initial_pieces = {'P': 8, 'N': 2, 'B': 2, 'R': 2, 'Q': 1, 'K': 1,
                          'p': 8, 'n': 2, 'b': 2, 'r': 2, 'q': 1, 'k': 1}
        current_pieces = {}
        for square in chess.SQUARES:
            p = self.board.piece_at(square)
            if p:
                sym = p.symbol()
                current_pieces[sym] = current_pieces.get(sym, 0) + 1
                
        for piece, count in initial_pieces.items():
            missing = count - current_pieces.get(piece, 0)
            if missing > 0:
                if piece.isupper():
                    captured_white.extend([piece] * missing)
                else:
                    captured_black.extend([piece] * missing)

        return {
            "id": self.id,
            "fen": self.board.fen(),
            "turn": turn_str,
            "is_game_over": self.is_game_over,
            "result": self.result,
            "config": self.config,
            "move_history": self.move_history,
            "last_move": last_move,
            "in_check": self.board.is_check(),
            "legal_moves": [m.uci() for m in self.board.legal_moves],
            "captured_white": captured_white,
            "captured_black": captured_black
        }

class GameManager:
    _instance = None
    
    @classmethod
    def _get_save_paths(cls):
        import tempfile
        paths = [
            os.path.join(tempfile.gettempdir(), "chess_mcp_games.json"),
            os.path.join(os.path.expanduser("~"), ".chess_mcp_games.json")
        ]
        unique_paths = []
        for p in paths:
            if p not in unique_paths:
                unique_paths.append(p)
        return unique_paths
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GameManager, cls).__new__(cls)
            cls._instance.games: Dict[str, GameInstance] = {}
            cls._instance._lock = threading.RLock()
            cls._instance.dashboard_listeners: List[asyncio.Queue] = []
            cls._instance._load_from_disk()
        return cls._instance

    def _save_to_disk(self):
        try:
            data = {}
            # 1. Read existing disk data to preserve games from other processes
            for path in self._get_save_paths():
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            disk_content = json.load(f)
                            if isinstance(disk_content, dict):
                                data.update(disk_content)
                    except Exception:
                        pass

            # 2. Update/Merge in-memory games
            for g_id, g in self.games.items():
                data[g_id] = {
                    "id": g.id,
                    "fen": g.board.fen(),
                    "config": g.config,
                    "move_history": g.move_history
                }

            # 3. Save merged data
            for path in self._get_save_paths():
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception as e:
                    import sys
                    print(f"Warning: Failed to save game state to {path}: {e}", file=sys.stderr)
        except Exception as e:
            import sys
            print(f"Warning: Failed to serialize game state: {e}", file=sys.stderr)

    def _load_from_disk(self):
        for path in self._get_save_paths():
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                for g_id, item in data.items():
                    if g_id not in self.games:
                        board = chess.Board(item["fen"])
                        ai = ChessAI() if item.get("config", {}).get("type") == "computer" else None
                        game = GameInstance(
                            id=g_id,
                            board=board,
                            config=item.get("config", {}),
                            ai=ai,
                            move_history=item.get("move_history", [])
                        )
                        self.games[g_id] = game
            except Exception as e:
                import sys
                print(f"Warning: Failed to load game state from {path}: {e}", file=sys.stderr)

    def create_game(self, config: dict) -> GameInstance:
        with self._lock:
            self._load_from_disk()
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
            self._save_to_disk()
            self._notify_dashboard("game_created", game_id)
            return game

    def get_game(self, game_id: str) -> Optional[GameInstance]:
        with self._lock:
            self._load_from_disk()
            return self.games.get(game_id)
        
    def clear_games(self, clear_all=True):
        with self._lock:
            if clear_all:
                self.games.clear()
            else:
                self.games = {g_id: g for g_id, g in self.games.items() if not g.is_game_over}
            
            data = {}
            for g_id, g in self.games.items():
                data[g_id] = {
                    "id": g.id,
                    "fen": g.board.fen(),
                    "config": g.config,
                    "move_history": g.move_history
                }
            for path in self._get_save_paths():
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            self._notify_dashboard("games_cleared", "")

    def list_games(self):
        with self._lock:
            self._load_from_disk()
            return [
                {
                    "id": g.id, 
                    "fen": g.board.fen(), 
                    "type": g.config.get("type"),
                    "difficulty": g.config.get("difficulty", 5),
                    "turn": "White" if g.board.turn == chess.WHITE else "Black",
                    "move_count": len(g.move_history),
                    "is_game_over": g.is_game_over,
                    "result": g.result
                } 
                for g in self.games.values()
            ]

    def _notify_dashboard(self, event_type: str, game_id: str):
        """Pushes updates to dashboard subscribers."""
        games_list = self.list_games()
        event_data = {
            "event_type": event_type,
            "game_id": game_id,
            "games": games_list
        }
        to_remove = []
        for q in self.dashboard_listeners:
            try:
                q.put_nowait(event_data)
            except Exception:
                to_remove.append(q)
        for q in to_remove:
            if q in self.dashboard_listeners:
                self.dashboard_listeners.remove(q)

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
            
        # Record move details before pushing
        san = game.board.san(move)
        turn_str = "White" if game.board.turn == chess.WHITE else "Black"
        captured = game.board.piece_at(move.to_square)
        captured_str = captured.symbol() if captured else None
        
        # Execute Move
        game.board.push(move)
        
        # Store move in history
        move_entry = {
            "move_number": (len(game.move_history) // 2) + 1,
            "turn": turn_str,
            "uci": move.uci(),
            "san": san,
            "fen": game.board.fen(),
            "captured": captured_str
        }
        game.move_history.append(move_entry)
        
        # Check Claim
        if claim_win:
            if not game.board.is_checkmate():
                 game.board.pop()
                 game.move_history.pop()
                 raise ValueError("Move rejected: You claimed Checkmate, but this move does not result in Checkmate.")
        
        # Notify waiters & SSE listeners
        game.move_event.set()
        game.move_event.clear() # Reset for next turn
        game.notify_listeners(event_type="move")
        self._save_to_disk()
        self._notify_dashboard("game_updated", game_id)
        
        # If vs Computer and it's Computer's turn now (and game not over)
        if game.config.get("type") == "computer" and not game.board.is_game_over():
            game.ai_task = asyncio.create_task(self._computer_turn(game))
            
        return "Move accepted"

    async def _computer_turn(self, game: GameInstance):
        """
        Calculates and executes computer move.
        """
        await asyncio.sleep(0.5)
        
        difficulty = game.config.get("difficulty", 5)
        ai_move = game.ai.get_move(game.board, difficulty)
        
        if ai_move:
            san = game.board.san(ai_move)
            turn_str = "White" if game.board.turn == chess.WHITE else "Black"
            captured = game.board.piece_at(ai_move.to_square)
            captured_str = captured.symbol() if captured else None
            
            game.board.push(ai_move)
            
            move_entry = {
                "move_number": (len(game.move_history) // 2) + 1,
                "turn": turn_str,
                "uci": ai_move.uci(),
                "san": san,
                "fen": game.board.fen(),
                "captured": captured_str
            }
            game.move_history.append(move_entry)
            
            # Notify waiters (Agent waiting for computer) & SSE listeners
            game.move_event.set()
            game.move_event.clear()
            game.notify_listeners(event_type="move")
            self._save_to_disk()
            self._notify_dashboard("game_updated", game.id)

            
