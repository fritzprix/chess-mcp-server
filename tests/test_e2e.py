import asyncio
import os
import sys
import re
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Ensure functionality of imports if run directly
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)


@pytest.mark.asyncio
async def test_stdio_safe_browser_open_keeps_mcp_alive(tmp_path):
    """Browser must open, but its stdout must not corrupt MCP stdio."""
    stamp = tmp_path / "opened"
    fake_browser = tmp_path / "fake_browser.py"
    fake_browser.write_text(
        "import pathlib\n"
        "print('browser output that would corrupt MCP stdio')\n"
        f"pathlib.Path(r'{stamp}').write_text('opened', encoding='utf-8')\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["BROWSER"] = f"{sys.executable} {fake_browser} %s"
    env["CHESS_MCP_DB_PATH"] = str(tmp_path / "games.sqlite3")
    # Avoid xdg-open taking precedence over BROWSER in some environments.
    env["PATH"] = str(tmp_path) + os.pathsep + env.get("PATH", "")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server"],
        env=env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=3.0)
            await asyncio.sleep(1.5)
            tools = await asyncio.wait_for(session.list_tools(), timeout=3.0)
            assert len(tools.tools) == 4
            assert stamp.exists(), "expected stdio-safe browser opener to be invoked"


@pytest.mark.asyncio
async def test_agent_vs_computer(tmp_path):
    print("Starting E2E Test: Agent vs Computer...")

    # Define server parameters
    # Running the module directly
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server"],
        env={**os.environ, "CHESS_MCP_DB_PATH": str(tmp_path / "games.sqlite3")}
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize
            await session.initialize()
            
            # List tools to verify connection
            tools = await session.list_tools()
            assert len(tools.tools) > 0, "No tools found on server"

            # --- Step 1: Create Game ---
            print("\n[Step 1] Creating Game (Agent White vs Computer)...")
            result = await session.call_tool(
                "createGame",
                arguments={"type": "computer", "color": "white", "difficulty": 1}
            )
            
            # Parse output
            content_text = result.content[0].text
            print(f"Server Response:\n{content_text}")
            
            # Extract Game ID
            match = re.search(r"Game ID: ([a-fA-F0-9\-]+)", content_text)
            assert match, "Could not find Game ID in server response"
            
            game_id = match.group(1)
            print(f"Game ID found: {game_id}")
            token_match = re.search(r"Player token: ([A-Za-z0-9_-]+)", content_text)
            assert token_match, "Could not find player token in server response"
            player_token = token_match.group(1)

            # --- Step 1.5: Test Invalid Move returns isError == True ---
            print("\n[Step 1.5] Testing Invalid Move 'e2e5'...")
            invalid_res = await session.call_tool(
                "finishTurn",
                arguments={
                    "game_id": game_id,
                    "move": "e2e5",
                    "player_token": player_token,
                }
            )
            assert invalid_res.isError is True, "Expected isError=True on illegal move"
            print("Invalid move correctly returned isError=True!")

            # --- Step 2: Make Move (e2e4) ---
            print("\n[Step 2] Making Move 'e2e4'...")
            result = await session.call_tool(
                "finishTurn",
                arguments={
                    "game_id": game_id,
                    "move": "e2e4",
                    "player_token": player_token,
                }
            )
            content_text = result.content[0].text
            print(f"Server Response:\n{content_text}")
            
            assert "Opponent is thinking" in content_text or "waitForNextTurn" in content_text, "Expected waiting for move message"

            # --- Step 3: Wait for Computer Move ---
            print("\n[Step 3] Waiting for Computer Turn...")
            
            result = await session.call_tool(
                "waitForNextTurn",
                arguments={
                    "game_id": game_id,
                    "player_token": player_token,
                }
            )
            content_text = result.content[0].text
            print(f"Server Response:\n{content_text}")
            
            assert "Timeout" not in content_text, "Timed out waiting for computer"
                
            # Verify board state
            assert "**FEN**" in content_text, "Did not receive board state"

    print("\nE2E Test COMPLETED SUCCESSFULLY.")


def test_mcp_dependency_version_upper_bound():
    """Regression test: pyproject.toml must enforce mcp < 2.0.0 to prevent FastMCP breakage."""
    pyproject_path = os.path.join(project_root, "pyproject.toml")
    with open(pyproject_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "<2.0.0" in content, "pyproject.toml missing '<2.0.0' upper bound for mcp dependency!"


def test_fastmcp_import_regression():
    """Regression test: FastMCP module import must succeed without ModuleNotFoundError."""
    from mcp.server.fastmcp import FastMCP
    assert FastMCP is not None


@pytest.mark.asyncio
async def test_fast_initialization_handshake(tmp_path):
    """Regression test: MCP initialize() handshake must complete quickly (< 2.0s)."""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "src.mcp_server"],
        env={**os.environ, "CHESS_MCP_DB_PATH": str(tmp_path / "games.sqlite3")}
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            start_time = asyncio.get_event_loop().time()
            init_res = await asyncio.wait_for(session.initialize(), timeout=2.0)
            elapsed = asyncio.get_event_loop().time() - start_time
            assert init_res is not None
            assert elapsed < 2.0, f"Initialize took too long: {elapsed:.2f}s"

