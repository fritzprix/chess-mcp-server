import pytest

from src.mcp_client import ChessMcpClient


def client_environment(tmp_path):
    return {
        "CHESS_MCP_DB_PATH": str(tmp_path / "games.sqlite3"),
        "BROWSER": "__chess_mcp_test_browser_does_not_exist__",
    }


@pytest.mark.asyncio
async def test_mcp_client_computer_white_scenario(tmp_path):
    async with ChessMcpClient(env=client_environment(tmp_path)) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "createGame",
            "joinGame",
            "finishTurn",
            "waitForNextTurn",
        }

        game = await client.create_game("computer", "white", difficulty=1)
        result = await client.finish_turn(game, "e2e4")

        assert result.isError is not True
        assert "waitForNextTurn" in client.text(result)

        result = await client.wait_for_next_turn(game)
        assert result.isError is not True
        assert "Timeout" not in client.text(result)
        assert "**FEN**" in client.text(result)


@pytest.mark.asyncio
async def test_mcp_client_computer_black_scenario(tmp_path):
    async with ChessMcpClient(env=client_environment(tmp_path)) as client:
        game = await client.create_game("computer", "black", difficulty=1)

        result = await client.wait_for_next_turn(game)
        assert result.isError is not True
        assert "**FEN**" in client.text(result)

        result = await client.finish_turn(game, "e7e5")
        assert result.isError is not True

        result = await client.wait_for_next_turn(game)
        assert result.isError is not True
        assert "Timeout" not in client.text(result)


@pytest.mark.asyncio
async def test_mcp_client_two_process_agent_scenario(tmp_path):
    environment = client_environment(tmp_path)
    async with ChessMcpClient(env=environment) as white_client:
        async with ChessMcpClient(env=environment) as black_client:
            white_game = await white_client.create_game("agent", "white")
            black_game = await black_client.join_game(white_game.game_id)

            result = await white_client.finish_turn(white_game, "e2e4")
            assert result.isError is not True

            result = await black_client.wait_for_next_turn(black_game)
            assert result.isError is not True
            assert "**Turn**: Black to move" in black_client.text(result)

            result = await black_client.finish_turn(black_game, "e7e5")
            assert result.isError is not True

            result = await white_client.wait_for_next_turn(white_game)
            assert result.isError is not True
            assert "**Turn**: White to move" in white_client.text(result)


@pytest.mark.asyncio
async def test_mcp_client_human_scenario_returns_ui(tmp_path):
    async with ChessMcpClient(env=client_environment(tmp_path)) as client:
        result = await client.call_tool(
            "createGame",
            {
                "type": "human",
                "color": "white",
                "difficulty": 5,
            },
        )

        assert "Game Created Successfully!" in client.text(result)
        assert client.has_embedded_resource(result)


@pytest.mark.asyncio
async def test_mcp_client_reconnect_reads_persisted_state(tmp_path):
    environment = client_environment(tmp_path)
    async with ChessMcpClient(env=environment) as client:
        game = await client.create_game("agent", "white")
        result = await client.finish_turn(game, "e2e4")
        assert result.isError is not True

    async with ChessMcpClient(env=environment) as reconnected_client:
        result = await reconnected_client.call_tool(
            "joinGame",
            {"game_id": game.game_id},
        )
        assert result.isError is not True
        assert "**Turn**: Black to move" in reconnected_client.text(result)
