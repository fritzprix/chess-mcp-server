import asyncio
import uuid
import chess
import threading
import json
import os
import time
from typing import Dict, Optional, List, Tuple, Union
from dataclasses import dataclass, field
from .chess_engine import ChessAI

ListenerEntry = Union[
    Tuple[asyncio.AbstractEventLoop, asyncio.Queue],
    asyncio.Queue,
]


def _captured_symbol(board: chess.Board, move: chess.Move) -> Optional[str]:
    """Return captured piece symbol, including en passant."""
    if board.is_en_passant(move):
        return chess.Piece(chess.PAWN, not board.turn).symbol()
    captured = board.piece_at(move.to_square)
    return captured.symbol() if captured else None


@dataclass
class GameInstance:
    id: str
    board: chess.Board
    config: dict
    # Thread-safe signal for waitForNextTurn (MCP loop ≠ uvicorn loop)
    move_event: threading.Event = field(default_factory=threading.Event)
    move_version: int = 0

    ai: Optional[ChessAI] = None
    ai_task: Optional[asyncio.Task] = None

    # History of moves for visual play trace & replay
    move_history: List[dict] = field(default_factory=list)

    listeners: List[ListenerEntry] = field(default_factory=list)

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

    @property
    def pgn_result(self) -> str:
        mapping = {"White wins": "1-0", "Black wins": "0-1", "Draw": "1/2-1/2"}
        return mapping.get(self.result or "", "*")

    def signal_move(self):
        """Wake waiters across threads without set/clear lost-wakeup races."""
        self.move_version += 1
        self.move_event.set()

    def notify_listeners(self, event_type: str = "update"):
        """Pushes state updates to all active SSE listener queues in a thread-safe manner."""
        data = self.get_full_state()
        data["event_type"] = event_type

        to_remove = []
        listeners_snapshot = list(self.listeners)
        for item in listeners_snapshot:
            try:
                if isinstance(item, tuple):
                    loop, q = item
                    if loop.is_running():
                        loop.call_soon_threadsafe(q.put_nowait, data)
                    else:
                        q.put_nowait(data)
                else:
                    item.put_nowait(data)
            except Exception:
                to_remove.append(item)
        for item in to_remove:
            if item in self.listeners:
                self.listeners.remove(item)

    def get_full_state(self) -> dict:
        """Returns comprehensive game state dictionary."""
        turn_str = "White" if self.board.turn == chess.WHITE else "Black"
        last_move = self.move_history[-1] if self.move_history else None

        captured_white = []
        captured_black = []

        initial_pieces = {
            "P": 8, "N": 2, "B": 2, "R": 2, "Q": 1, "K": 1,
            "p": 8, "n": 2, "b": 2, "r": 2, "q": 1, "k": 1,
        }
        current_pieces: Dict[str, int] = {}
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
            "captured_black": captured_black,
            "move_version": self.move_version,
        }


class GameManager:
    _instance = None

    @classmethod
    def _get_save_paths(cls):
        import tempfile
        paths = [
            os.path.join(tempfile.gettempdir(), "chess_mcp_games.json"),
            os.path.join(os.path.expanduser("~"), ".chess_mcp_games.json"),
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
            cls._instance.dashboard_listeners: List[ListenerEntry] = []
            cls._instance._load_from_disk()
        return cls._instance

    def _atomic_write_json(self, path: str, data: dict):
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _save_to_disk(self):
        try:
            data = {}
            for path in self._get_save_paths():
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            disk_content = json.load(f)
                            if isinstance(disk_content, dict):
                                data.update(disk_content)
                    except Exception:
                        pass

            for g_id, g in self.games.items():
                data[g_id] = {
                    "id": g.id,
                    "fen": g.board.fen(),
                    "config": g.config,
                    "move_history": g.move_history,
                }

            for path in self._get_save_paths():
                try:
                    self._atomic_write_json(path, data)
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
                    disk_history = item.get("move_history", [])
                    if g_id not in self.games:
                        board = chess.Board(item["fen"])
                        ai = ChessAI() if item.get("config", {}).get("type") == "computer" else None
                        game = GameInstance(
                            id=g_id,
                            board=board,
                            config=item.get("config", {}),
                            ai=ai,
                            move_history=disk_history,
                        )
                        self.games[g_id] = game
                    else:
                        existing = self.games[g_id]
                        if len(disk_history) > len(existing.move_history):
                            existing.board = chess.Board(item["fen"])
                            existing.move_history = disk_history
                            existing.signal_move()
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
                ai=ai,
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
            games_to_clear = (
                list(self.games.values())
                if clear_all
                else [g for g in self.games.values() if g.is_game_over]
            )
            for g in games_to_clear:
                if g.ai_task and not g.ai_task.done():
                    g.ai_task.cancel()

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
                    "move_history": g.move_history,
                }
            for path in self._get_save_paths():
                try:
                    self._atomic_write_json(path, data)
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
                    "result": g.result,
                }
                for g in self.games.values()
            ]

    def _notify_dashboard(self, event_type: str, game_id: str):
        """Pushes updates to dashboard subscribers in a thread-safe manner."""
        games_list = self.list_games()
        event_data = {
            "event_type": event_type,
            "game_id": game_id,
            "games": games_list,
        }
        to_remove = []
        listeners_snapshot = list(self.dashboard_listeners)
        for item in listeners_snapshot:
            try:
                if isinstance(item, tuple):
                    loop, q = item
                    if loop.is_running():
                        loop.call_soon_threadsafe(q.put_nowait, event_data)
                    else:
                        q.put_nowait(event_data)
                else:
                    item.put_nowait(event_data)
            except Exception:
                to_remove.append(item)
        for item in to_remove:
            if item in self.dashboard_listeners:
                self.dashboard_listeners.remove(item)

    def schedule_computer_turn(self, game: GameInstance):
        """Schedule AI move on the running loop, or a daemon thread if none."""
        try:
            loop = asyncio.get_running_loop()
            game.ai_task = loop.create_task(self._computer_turn(game))
        except RuntimeError:
            def _run():
                asyncio.run(self._computer_turn(game))

            threading.Thread(target=_run, daemon=True).start()

    async def wait_until_turn(
        self,
        game: GameInstance,
        my_color: chess.Color,
        timeout: float = 30.0,
    ) -> str:
        """
        Wait until it is my_color's turn or the game ends.
        Returns 'my_turn', 'game_over', or 'timeout'.
        Uses move_version to avoid set/clear lost-wakeup races.
        """
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._load_from_disk()
                if game.is_game_over:
                    return "game_over"
                if game.board.turn == my_color:
                    return "my_turn"
                version = game.move_version

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout"

            wait_slice = min(remaining, 0.5)

            def _block_wait():
                end = time.monotonic() + wait_slice
                while game.move_version == version and time.monotonic() < end:
                    game.move_event.wait(timeout=0.1)
                    game.move_event.clear()

            await asyncio.to_thread(_block_wait)

    async def make_move(self, game_id: str, move_uci: str, claim_win: bool = False) -> str:
        """
        Executes a move.
        Returns 'Move accepted' or raises ValueError.
        Triggers computer move if applicable.
        """
        schedule_ai = False
        with self._lock:
            self._load_from_disk()
            game = self.games.get(game_id)
            if not game:
                raise ValueError(f"Game {game_id} not found")

            try:
                move = chess.Move.from_uci(move_uci)
            except ValueError:
                raise ValueError(
                    f"Invalid UCI move format: '{move_uci}'. "
                    "Please use standard format like 'e2e4' (start_square+end_square)."
                )

            if move not in game.board.legal_moves:
                sample_moves = ", ".join([str(m) for m in list(game.board.legal_moves)[:3]])
                raise ValueError(
                    f"Illegal move: '{move_uci}'. Review the board state. "
                    f"Sample legal moves: {sample_moves}..."
                )

            san = game.board.san(move)
            turn_str = "White" if game.board.turn == chess.WHITE else "Black"
            captured_str = _captured_symbol(game.board, move)

            game.board.push(move)

            move_entry = {
                "move_number": (len(game.move_history) // 2) + 1,
                "turn": turn_str,
                "uci": move.uci(),
                "san": san,
                "fen": game.board.fen(),
                "captured": captured_str,
            }
            game.move_history.append(move_entry)

            if claim_win:
                if not game.board.is_checkmate():
                    game.board.pop()
                    game.move_history.pop()
                    raise ValueError(
                        "Move rejected: You claimed Checkmate, but this move does not result in Checkmate."
                    )

            game.signal_move()
            game.notify_listeners(event_type="move")
            self._save_to_disk()
            self._notify_dashboard("game_updated", game_id)

            if game.config.get("type") == "computer" and not game.board.is_game_over():
                schedule_ai = True

        if schedule_ai:
            self.schedule_computer_turn(game)

        return "Move accepted"

    async def _computer_turn(self, game: GameInstance):
        """Calculates and executes computer move without blocking the event loop."""
        await asyncio.sleep(0.5)

        with self._lock:
            if game.is_game_over or game.ai is None:
                return
            if game.id not in self.games:
                return
            difficulty = game.config.get("difficulty", 5)
            board_copy = game.board.copy()

        ai_move = await asyncio.to_thread(game.ai.get_move, board_copy, difficulty)
        if not ai_move:
            return

        with self._lock:
            if game.is_game_over or game.id not in self.games:
                return
            if ai_move not in game.board.legal_moves:
                return

            san = game.board.san(ai_move)
            turn_str = "White" if game.board.turn == chess.WHITE else "Black"
            captured_str = _captured_symbol(game.board, ai_move)

            game.board.push(ai_move)

            move_entry = {
                "move_number": (len(game.move_history) // 2) + 1,
                "turn": turn_str,
                "uci": ai_move.uci(),
                "san": san,
                "fen": game.board.fen(),
                "captured": captured_str,
            }
            game.move_history.append(move_entry)

            game.signal_move()
            game.notify_listeners(event_type="move")
            self._save_to_disk()
            self._notify_dashboard("game_updated", game.id)
