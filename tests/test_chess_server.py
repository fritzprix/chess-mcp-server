import sys
import os
import pytest
import chess

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.game_state import GameManager, GameInstance
from src.chess_engine import ChessAI
from src.rendering import render_board_to_markdown

@pytest.fixture(autouse=True)
def reset_singleton(tmp_path, monkeypatch):
    monkeypatch.setenv("CHESS_MCP_DB_PATH", str(tmp_path / "games.sqlite3"))
    GameManager._instance = None
    yield
    if GameManager._instance:
        for g in GameManager._instance.games.values():
            if hasattr(g, 'ai_task') and g.ai_task and not g.ai_task.done():
                g.ai_task.cancel()

def test_create_game():
    manager = GameManager()
    config = {"type": "computer", "difficulty": 1}
    game = manager.create_game(config)
    assert game.id is not None
    assert game.ai is not None
    assert game.config["difficulty"] == 1

@pytest.mark.asyncio
async def test_make_move_logic():
    manager = GameManager()
    config = {"type": "agent"}
    game = manager.create_game(config)
    
    await manager.make_move(game.id, "e2e4")
    assert game.board.piece_at(chess.E4).symbol() == "P"
    assert game.board.turn == chess.BLACK
    assert len(game.move_history) == 1
    assert game.move_history[0]["san"] == "e4"

@pytest.mark.asyncio
async def test_invalid_move():
    manager = GameManager()
    config = {"type": "agent"}
    game = manager.create_game(config)
    
    with pytest.raises(ValueError):
        await manager.make_move(game.id, "e2e5")

@pytest.mark.asyncio
async def test_checkmate_claim_invalid():
    manager = GameManager()
    config = {"type": "agent"}
    game = manager.create_game(config)
    
    with pytest.raises(ValueError, match="Move rejected: You claimed Checkmate"):
        await manager.make_move(
            game.id,
            "e2e4",
            claim_win=True,
        )

def test_engine_level_1():
    ai = ChessAI()
    board = chess.Board()
    move = ai.get_move(board, level=1)
    assert move in board.legal_moves


def test_engine_difficulty_errors_do_not_increase_with_level():
    ai = ChessAI()
    error_rates = [ai.levels[level]["error_rate"] for level in range(1, 11)]
    assert error_rates == sorted(error_rates, reverse=True)


def test_engine_top_n_sampling_decreases_with_level():
    ai = ChessAI()
    top_n_values = [ai.levels[level]["top_n"] for level in range(1, 11)]
    assert top_n_values == sorted(top_n_values, reverse=True)
    assert ai.levels[5]["top_n"] == 3
    assert ai.levels[10]["top_n"] == 2


def test_engine_stops_on_custom_lone_king_loss():
    ai = ChessAI()
    board = chess.Board("7k/8/8/8/8/8/8/K6q w - - 0 1")
    assert ai.get_move(board, level=10) is None


def test_rendering_content():
    md = render_board_to_markdown(chess.Board().fen(), player_color="White")
    assert "**Turn**: White to move" in md
    assert "**FEN**:" in md
    assert "**You are playing**: White" in md
    assert "Legend" in md
    assert " P " in md

@pytest.mark.asyncio
async def test_actionable_error_format():
    manager = GameManager()
    config = {"type": "agent"}
    game = manager.create_game(config)
    
    with pytest.raises(ValueError) as exc_info:
        await manager.make_move(
            game.id,
            "invalid_format",
        )
    assert "Please use standard format" in str(exc_info.value)
    
    with pytest.raises(ValueError) as exc_info:
        await manager.make_move(game.id, "e2e8")
    assert "Sample legal moves:" in str(exc_info.value)


@pytest.mark.asyncio
async def test_wait_until_turn_no_lost_wakeup():
    """Opponent move before wait must not hang (set/clear lost-wakeup regression)."""
    manager = GameManager()
    game = manager.create_game({"type": "agent", "color": "white"})
    manager.join_game(game.id)
    await manager.make_move(game.id, "e2e4")
    await manager.make_move(game.id, "e7e5")  # back to white — signal already fired
    status = await manager.wait_until_turn(game, chess.WHITE, timeout=1.0)
    assert status == "my_turn"


@pytest.mark.asyncio
async def test_state_reloads_from_shared_sqlite_store():
    manager = GameManager()
    game = manager.create_game({"type": "agent", "color": "white"})
    await manager.make_move(game.id, "e2e4")

    GameManager._instance = None
    reloaded_manager = GameManager()
    reloaded_game = reloaded_manager.get_game(game.id)

    assert reloaded_game is not None
    assert reloaded_game.board.fen() == game.board.fen()
    assert reloaded_game.revision == 1


@pytest.mark.asyncio
async def test_en_passant_capture_recorded():
    manager = GameManager()
    game = manager.create_game({"type": "agent"})
    manager.join_game(game.id)
    await manager.make_move(game.id, "e2e4")
    await manager.make_move(game.id, "a7a6")
    await manager.make_move(game.id, "e4e5")
    await manager.make_move(game.id, "d7d5")
    await manager.make_move(game.id, "e5d6")
    assert game.move_history[-1]["captured"] == "p"


def test_pgn_result_mapping():
    board = chess.Board()
    # Fool's mate
    board.push_san("f3")
    board.push_san("e5")
    board.push_san("g4")
    board.push_san("Qh4")
    game = GameInstance(id="test", board=board, config={})
    assert game.result == "Black wins"
    assert game.pgn_result == "0-1"


def test_lone_king_is_a_loss():
    white_wins = GameInstance(
        id="white-wins",
        board=chess.Board("7k/8/8/8/8/8/8/KQ6 w - - 0 1"),
        config={},
    )
    assert white_wins.is_game_over
    assert white_wins.result == "White wins"

    black_wins = GameInstance(
        id="black-wins",
        board=chess.Board("7k/8/8/8/8/8/8/K6q w - - 0 1"),
        config={},
    )
    assert black_wins.is_game_over
    assert black_wins.result == "Black wins"

    king_only_draw = GameInstance(
        id="draw",
        board=chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1"),
        config={},
    )
    assert king_only_draw.is_game_over
    assert king_only_draw.result == "Draw"


def test_minimax_maximizing_uses_side_to_move():
    ai = ChessAI()
    board = chess.Board("r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1N1 w KQkq - 4 4")
    move = ai.get_move(board, level=10)
    assert move.uci() == "h5f7"


def test_create_game_opens_board_in_browser(monkeypatch):
    import time
    from src import mcp_server

    GameManager._instance = None
    opened: list[str] = []

    def capture_open(url: str) -> None:
        opened.append(url)

    monkeypatch.setattr(mcp_server, "open_browser_stdio_safe", capture_open)
    monkeypatch.setattr(mcp_server, "get_dashboard_url", lambda: "http://127.0.0.1:8080")

    mcp_server.createGame(type="computer", color="white", difficulty=1)

    deadline = time.time() + 1.0
    while time.time() < deadline and not opened:
        time.sleep(0.05)

    assert len(opened) == 1
    assert opened[0].startswith("http://127.0.0.1:8080/game/")
    assert "/game/" in opened[0]

