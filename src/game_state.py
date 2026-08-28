import asyncio
import hmac
import secrets
import uuid
import chess
import threading
import json
import os
import sqlite3
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
    revision: int = 0
    ai_running: bool = False
    player_token: Optional[str] = None
    white_token: Optional[str] = None
    black_token: Optional[str] = None

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
            "config": dict(self.config),
            "move_history": [dict(move) for move in self.move_history],
            "last_move": dict(last_move) if last_move else None,
            "in_check": self.board.is_check(),
            "legal_moves": [m.uci() for m in self.board.legal_moves],
            "captured_white": captured_white,
            "captured_black": captured_black,
            "move_version": self.move_version,
            "revision": self.revision,
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

    @classmethod
    def _get_database_path(cls) -> str:
        configured_path = os.environ.get("CHESS_MCP_DB_PATH")
        if configured_path:
            return os.path.abspath(os.path.expanduser(configured_path))
        return os.path.join(os.path.expanduser("~"), ".chess_mcp_games.sqlite3")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GameManager, cls).__new__(cls)
            cls._instance.games: Dict[str, GameInstance] = {}
            cls._instance._lock = threading.RLock()
            cls._instance.dashboard_listeners: List[ListenerEntry] = []
            cls._instance._db_path = cls._get_database_path()
            cls._instance._initialize_database()
            cls._instance._migrate_legacy_json()
            cls._instance._load_from_disk()
        return cls._instance

    def _connect_database(self) -> sqlite3.Connection:
        directory = os.path.dirname(self._db_path) or "."
        os.makedirs(directory, exist_ok=True)
        connection = sqlite3.connect(
            self._db_path,
            timeout=30.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_database(self) -> None:
        with self._connect_database() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS games (
                    id TEXT PRIMARY KEY,
                    fen TEXT NOT NULL,
                    config TEXT NOT NULL,
                    move_history TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    white_token TEXT,
                    black_token TEXT,
                    ai_claim_token TEXT,
                    ai_claimed_until REAL
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(games)").fetchall()
            }
            column_types = {
                "white_token": "TEXT",
                "black_token": "TEXT",
                "ai_claim_token": "TEXT",
                "ai_claimed_until": "REAL",
            }
            for column, column_type in column_types.items():
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE games ADD COLUMN {column} {column_type}"
                    )

    def _migrate_legacy_json(self) -> None:
        with self._connect_database() as connection:
            migrated = connection.execute(
                "SELECT value FROM metadata WHERE key = 'legacy_json_migrated'"
            ).fetchone()
            if migrated is not None:
                return

            connection.execute("BEGIN IMMEDIATE")
            try:
                for path in self._get_save_paths():
                    if not os.path.exists(path):
                        continue
                    try:
                        with open(path, "r", encoding="utf-8") as file:
                            data = json.load(file)
                    except (OSError, ValueError):
                        continue

                    if not isinstance(data, dict):
                        continue

                    for game_id, item in data.items():
                        if not isinstance(item, dict):
                            continue
                        fen = item.get("fen")
                        config = item.get("config", {})
                        history = item.get("move_history", [])
                        if (
                            not isinstance(game_id, str)
                            or not isinstance(fen, str)
                            or not isinstance(config, dict)
                            or not isinstance(history, list)
                        ):
                            continue
                        try:
                            chess.Board(fen)
                            json.dumps(history)
                            json.dumps(config)
                        except (ValueError, TypeError):
                            continue
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO games
                                (id, fen, config, move_history, revision)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                game_id,
                                fen,
                                json.dumps(config, ensure_ascii=False),
                                json.dumps(history, ensure_ascii=False),
                                len(history),
                            ),
                        )

                connection.execute(
                    """
                    INSERT INTO metadata (key, value)
                    VALUES ('legacy_json_migrated', '1')
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _load_from_disk(self):
        with self._connect_database() as connection:
            rows = connection.execute(
                """
                SELECT id, fen, config, move_history, revision,
                       white_token, black_token, ai_claimed_until
                FROM games
                """
            ).fetchall()

        stored_ids = {str(row["id"]) for row in rows}
        ai_claim_deadlines = {
            str(row["id"]): row["ai_claimed_until"]
            for row in rows
        }
        for game_id in list(self.games):
            if game_id not in stored_ids:
                self._cancel_ai_task(self.games[game_id])
                del self.games[game_id]

        for row in rows:
            game_id = str(row["id"])
            try:
                board = chess.Board(row["fen"])
                config = json.loads(row["config"])
                history = json.loads(row["move_history"])
                revision = int(row["revision"])
                if not isinstance(config, dict) or not isinstance(history, list):
                    raise ValueError("Stored game state is invalid")
            except (ValueError, TypeError, json.JSONDecodeError):
                continue

            existing = self.games.get(game_id)
            if existing is None:
                self.games[game_id] = GameInstance(
                    id=game_id,
                    board=board,
                    config=config,
                    ai=ChessAI() if config.get("type") == "computer" else None,
                    move_history=history,
                    revision=revision,
                    white_token=row["white_token"],
                    black_token=row["black_token"],
                )
                continue

            if existing.revision != revision:
                existing.board = board
                existing.config = config
                existing.move_history = history
                existing.revision = revision
                existing.white_token = row["white_token"]
                existing.black_token = row["black_token"]
                existing.signal_move()

        for game in self.games.values():
            if (
                game.ai is not None
                and not game.is_game_over
                and game.board.turn
                == (
                    chess.BLACK
                    if game.config.get("color", "white") == "white"
                    else chess.WHITE
                )
                and (
                    ai_claim_deadlines.get(game.id) is None
                    or ai_claim_deadlines[game.id] <= time.time()
                )
            ):
                self.schedule_computer_turn(game)

    @staticmethod
    def _cancel_ai_task(game: GameInstance) -> None:
        task = game.ai_task
        if task is not None and not task.done():
            loop = task.get_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(task.cancel)
            else:
                task.cancel()
        game.ai_task = None
        game.ai_running = False

    def create_game(self, config: dict) -> GameInstance:
        with self._lock:
            self._load_from_disk()
            board = chess.Board()
            ai = ChessAI() if config.get("type") == "computer" else None
            creator_token = secrets.token_urlsafe(24)
            creator_color = config.get("color", "white")
            white_token = creator_token if creator_color == "white" else None
            black_token = creator_token if creator_color == "black" else None
            if config.get("type") == "human":
                if white_token is None:
                    white_token = secrets.token_urlsafe(24)
                if black_token is None:
                    black_token = secrets.token_urlsafe(24)

            with self._connect_database() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    for _ in range(5):
                        game_id = str(uuid.uuid4())[:8]
                        try:
                            connection.execute(
                                """
                                INSERT INTO games
                                    (
                                        id, fen, config, move_history, revision,
                                        white_token, black_token
                                    )
                                VALUES (?, ?, ?, ?, 0, ?, ?)
                                """,
                                (
                                    game_id,
                                    board.fen(),
                                    json.dumps(config, ensure_ascii=False),
                                    "[]",
                                    white_token,
                                    black_token,
                                ),
                            )
                            break
                        except sqlite3.IntegrityError:
                            continue
                    else:
                        raise RuntimeError("Could not allocate a unique game ID")
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise

            game = GameInstance(
                id=game_id,
                board=board,
                config=dict(config),
                ai=ai,
                revision=0,
                player_token=creator_token,
                white_token=white_token,
                black_token=black_token,
            )
            self.games[game_id] = game
            self._notify_dashboard("game_created", game_id)
            if config.get("type") == "computer" and config.get("color", "white") == "black":
                self.schedule_computer_turn(game)
            return game

    def get_game(self, game_id: str) -> Optional[GameInstance]:
        with self._lock:
            self._load_from_disk()
            return self.games.get(game_id)

    def get_game_state(self, game_id: str) -> Optional[dict]:
        """Return an atomic state snapshot from the shared store."""
        with self._lock:
            self._load_from_disk()
            game = self.games.get(game_id)
            return game.get_full_state() if game else None

    def join_game(self, game_id: str) -> Tuple[GameInstance, str, chess.Color]:
        """Atomically assign the remaining player slot in an agent game."""
        with self._lock:
            self._load_from_disk()
            with self._connect_database() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT id, fen, config, move_history, revision,
                           white_token, black_token
                    FROM games
                    WHERE id = ?
                    """,
                    (game_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Game {game_id} not found")

                config = json.loads(row["config"])
                if config.get("type") != "agent":
                    raise ValueError("Only agent games can be joined by another agent")

                white_token = row["white_token"]
                black_token = row["black_token"]
                if white_token is None:
                    joined_color = chess.WHITE
                    token_column = "white_token"
                elif black_token is None:
                    joined_color = chess.BLACK
                    token_column = "black_token"
                else:
                    raise ValueError("Game already has two players")

                player_token = secrets.token_urlsafe(24)
                updated = connection.execute(
                    f"""
                    UPDATE games
                    SET {token_column} = ?, revision = revision + 1
                    WHERE id = ? AND revision = ?
                    """,
                    (player_token, game_id, row["revision"]),
                )
                if updated.rowcount != 1:
                    raise RuntimeError(f"Game {game_id} changed while joining")
                connection.commit()

            game = self.games.get(game_id)
            if game is None:
                self._load_from_disk()
                game = self.games.get(game_id)
            if game is None:
                raise RuntimeError(f"Game {game_id} disappeared while joining")
            game.revision = int(row["revision"]) + 1
            if joined_color == chess.WHITE:
                game.white_token = player_token
            else:
                game.black_token = player_token
            return game, player_token, joined_color

    def get_player_color(
        self,
        game_id: str,
        player_token: Optional[str],
    ) -> chess.Color:
        """Resolve a player's side from the persisted session token."""
        with self._lock:
            self._load_from_disk()
            with self._connect_database() as connection:
                row = connection.execute(
                    """
                    SELECT config, white_token, black_token
                    FROM games
                    WHERE id = ?
                    """,
                    (game_id,),
                ).fetchone()
            if row is None:
                raise ValueError(f"Game {game_id} not found")

            if player_token:
                if row["white_token"] and hmac.compare_digest(
                    row["white_token"], player_token
                ):
                    return chess.WHITE
                if row["black_token"] and hmac.compare_digest(
                    row["black_token"], player_token
                ):
                    return chess.BLACK

            if row["white_token"] is not None or row["black_token"] is not None:
                raise ValueError("Player token is not authorized for this game")

            config = json.loads(row["config"])
            return (
                chess.WHITE
                if config.get("color", "white") == "white"
                else chess.BLACK
            )

    def clear_games(self, clear_all=True):
        with self._lock:
            self._load_from_disk()
            games_to_clear = (
                list(self.games.values())
                if clear_all
                else [g for g in self.games.values() if g.is_game_over]
            )
            for g in games_to_clear:
                self._cancel_ai_task(g)

            game_ids = [g.id for g in games_to_clear]
            if game_ids:
                with self._connect_database() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        connection.executemany(
                            "DELETE FROM games WHERE id = ?",
                            ((game_id,) for game_id in game_ids),
                        )
                        connection.commit()
                    except Exception:
                        connection.rollback()
                        raise

            for game_id in game_ids:
                self.games.pop(game_id, None)
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
        with self._lock:
            if game.ai_running or (game.ai_task and not game.ai_task.done()):
                return
            game.ai_running = True

        try:
            loop = asyncio.get_running_loop()
            async def run_turn():
                try:
                    await self._computer_turn(game)
                finally:
                    with self._lock:
                        game.ai_running = False
                        game.ai_task = None

            game.ai_task = loop.create_task(run_turn())
        except RuntimeError:
            def _run():
                try:
                    asyncio.run(self._computer_turn(game))
                finally:
                    with self._lock:
                        game.ai_running = False
                        game.ai_task = None

            threading.Thread(target=_run, daemon=True).start()

    def _claim_ai_turn(self, game_id: str):
        """Claim an AI turn atomically so only one process calculates it."""
        with self._connect_database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, fen, config, move_history, revision,
                       ai_claim_token, ai_claimed_until
                FROM games
                WHERE id = ?
                """,
                (game_id,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None

            try:
                board = chess.Board(row["fen"])
                config = json.loads(row["config"])
                history = json.loads(row["move_history"])
                revision = int(row["revision"])
                if not isinstance(config, dict) or not isinstance(history, list):
                    raise ValueError("Stored game state is invalid")
            except (ValueError, TypeError, json.JSONDecodeError):
                connection.rollback()
                return None

            ai_color = (
                chess.BLACK
                if config.get("color", "white") == "white"
                else chess.WHITE
            )
            claimed_until = row["ai_claimed_until"]
            if (
                config.get("type") != "computer"
                or board.is_game_over()
                or board.turn != ai_color
                or (claimed_until is not None and claimed_until > time.time())
            ):
                connection.commit()
                return None

            claim_token = uuid.uuid4().hex
            updated = connection.execute(
                """
                UPDATE games
                SET ai_claim_token = ?, ai_claimed_until = ?
                WHERE id = ? AND revision = ?
                  AND (
                      ai_claimed_until IS NULL
                      OR ai_claimed_until <= ?
                  )
                """,
                (claim_token, time.time() + 300.0, game_id, revision, time.time()),
            )
            if updated.rowcount != 1:
                connection.commit()
                return None
            connection.commit()
            return board, config, history, revision, claim_token

    def _release_ai_claim(self, game_id: str, revision: int, claim_token: str) -> None:
        with self._connect_database() as connection:
            connection.execute(
                """
                UPDATE games
                SET ai_claim_token = NULL, ai_claimed_until = NULL
                WHERE id = ? AND revision = ? AND ai_claim_token = ?
                """,
                (game_id, revision, claim_token),
            )

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
                if self.games.get(game.id) is not game:
                    return "game_not_found"
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

    async def make_move(
        self,
        game_id: str,
        move_uci: str,
        claim_win: bool = False,
        player_token: Optional[str] = None,
    ) -> str:
        """
        Executes a move.
        Returns 'Move accepted' or raises ValueError.
        Triggers computer move if applicable.
        """
        schedule_ai = False
        with self._lock:
            self._load_from_disk()
            with self._connect_database() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT id, fen, config, move_history, revision,
                           white_token, black_token
                    FROM games
                    WHERE id = ?
                    """,
                    (game_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Game {game_id} not found")

                try:
                    board = chess.Board(row["fen"])
                    config = json.loads(row["config"])
                    history = json.loads(row["move_history"])
                    revision = int(row["revision"])
                    if not isinstance(config, dict) or not isinstance(history, list):
                        raise ValueError("Stored game state is invalid")
                except (ValueError, TypeError, json.JSONDecodeError) as error:
                    raise RuntimeError(f"Stored game {game_id} is invalid: {error}") from error

                expected_token = (
                    row["white_token"]
                    if board.turn == chess.WHITE
                    else row["black_token"]
                )
                has_player_tokens = (
                    row["white_token"] is not None
                    or row["black_token"] is not None
                )
                if has_player_tokens and expected_token is None:
                    raise ValueError("No player is assigned to the current turn")
                if expected_token is not None:
                    if player_token is None:
                        raise ValueError("A player token is required to move this game")
                    if not hmac.compare_digest(expected_token, player_token):
                        raise ValueError("Player token is not authorized for the current turn")

                try:
                    move = chess.Move.from_uci(move_uci)
                except ValueError:
                    raise ValueError(
                        f"Invalid UCI move format: '{move_uci}'. "
                        "Please use standard format like 'e2e4' (start_square+end_square)."
                    )

                if move not in board.legal_moves:
                    sample_moves = ", ".join([str(m) for m in list(board.legal_moves)[:3]])
                    raise ValueError(
                        f"Illegal move: '{move_uci}'. Review the board state. "
                        f"Sample legal moves: {sample_moves}..."
                    )

                san = board.san(move)
                turn_str = "White" if board.turn == chess.WHITE else "Black"
                captured_str = _captured_symbol(board, move)
                board.push(move)

                move_entry = {
                    "move_number": (len(history) // 2) + 1,
                    "turn": turn_str,
                    "uci": move.uci(),
                    "san": san,
                    "fen": board.fen(),
                    "captured": captured_str,
                }
                history.append(move_entry)

                if claim_win and not board.is_checkmate():
                    raise ValueError(
                        "Move rejected: You claimed Checkmate, but this move does not result in Checkmate."
                    )

                new_revision = revision + 1
                updated = connection.execute(
                    """
                    UPDATE games
                    SET fen = ?, config = ?, move_history = ?, revision = ?,
                        ai_claim_token = NULL, ai_claimed_until = NULL
                    WHERE id = ? AND revision = ?
                    """,
                    (
                        board.fen(),
                        json.dumps(config, ensure_ascii=False),
                        json.dumps(history, ensure_ascii=False),
                        new_revision,
                        game_id,
                        revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise RuntimeError(f"Game {game_id} changed while the move was being submitted")
                connection.commit()

            game = self.games.get(game_id)
            if game is None:
                game = GameInstance(
                    id=game_id,
                    board=board,
                    config=config,
                    ai=ChessAI() if config.get("type") == "computer" else None,
                    move_history=history,
                    revision=new_revision,
                    white_token=row["white_token"],
                    black_token=row["black_token"],
                )
                self.games[game_id] = game
            else:
                game.board = board
                game.config = config
                game.move_history = history
                game.revision = new_revision
                game.white_token = row["white_token"]
                game.black_token = row["black_token"]

            game.signal_move()
            game.notify_listeners(event_type="move")
            self._notify_dashboard("game_updated", game_id)

            if (
                game.config.get("type") == "computer"
                and not game.board.is_game_over()
            ):
                user_color = (
                    chess.WHITE
                    if game.config.get("color", "white") == "white"
                    else chess.BLACK
                )
                schedule_ai = game.board.turn != user_color

        if schedule_ai:
            self.schedule_computer_turn(game)

        return "Move accepted"

    async def _computer_turn(self, game: GameInstance):
        """Calculates and executes computer move without blocking the event loop."""
        await asyncio.sleep(0.5)

        claimed = self._claim_ai_turn(game.id)
        if claimed is None:
            return
        board_copy, config, history, revision, claim_token = claimed
        ai = game.ai or ChessAI()
        difficulty = config.get("difficulty", 5)
        try:
            ai_move = await asyncio.to_thread(ai.get_move, board_copy, difficulty)
        except (Exception, asyncio.CancelledError):
            self._release_ai_claim(game.id, revision, claim_token)
            raise
        if not ai_move:
            self._release_ai_claim(game.id, revision, claim_token)
            return

        with self._lock:
            with self._connect_database() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT fen, config, move_history, revision
                    FROM games
                    WHERE id = ? AND revision = ? AND ai_claim_token = ?
                    """,
                    (game.id, revision, claim_token),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return

                board = chess.Board(row["fen"])
                current_config = json.loads(row["config"])
                current_history = json.loads(row["move_history"])
                if ai_move not in board.legal_moves:
                    connection.execute(
                        """
                        UPDATE games
                        SET ai_claim_token = NULL, ai_claimed_until = NULL
                        WHERE id = ? AND revision = ? AND ai_claim_token = ?
                        """,
                        (game.id, revision, claim_token),
                    )
                    connection.commit()
                    return

                san = board.san(ai_move)
                turn_str = "White" if board.turn == chess.WHITE else "Black"
                captured_str = _captured_symbol(board, ai_move)
                board.push(ai_move)
                current_history.append(
                    {
                        "move_number": (len(current_history) // 2) + 1,
                        "turn": turn_str,
                        "uci": ai_move.uci(),
                        "san": san,
                        "fen": board.fen(),
                        "captured": captured_str,
                    }
                )
                updated = connection.execute(
                    """
                    UPDATE games
                    SET fen = ?, config = ?, move_history = ?, revision = ?,
                        ai_claim_token = NULL, ai_claimed_until = NULL
                    WHERE id = ? AND revision = ? AND ai_claim_token = ?
                    """,
                    (
                        board.fen(),
                        json.dumps(current_config, ensure_ascii=False),
                        json.dumps(current_history, ensure_ascii=False),
                        revision + 1,
                        game.id,
                        revision,
                        claim_token,
                    ),
                )
                if updated.rowcount != 1:
                    connection.commit()
                    return
                connection.commit()

            game.board = board
            game.config = current_config
            game.move_history = current_history
            game.revision = revision + 1
            game.signal_move()
            game.notify_listeners(event_type="move")
            self._notify_dashboard("game_updated", game.id)
