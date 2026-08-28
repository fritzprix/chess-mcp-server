import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, EmbeddedResource, TextContent


@dataclass(frozen=True)
class GameSession:
    game_id: str
    player_token: str
    color: str


class ChessMcpClient:
    """Small async MCP client for driving a local Chess MCP server."""

    def __init__(
        self,
        command: str = sys.executable,
        args: Optional[Sequence[str]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        server_env = os.environ.copy()
        if env:
            server_env.update(env)
        self._server_parameters = StdioServerParameters(
            command=command,
            args=list(args or ["-m", "src.mcp_server"]),
            env=server_env,
        )
        self._exit_stack: Optional[AsyncExitStack] = None
        self.session: Optional[ClientSession] = None

    async def __aenter__(self) -> "ChessMcpClient":
        self._exit_stack = AsyncExitStack()
        read_stream, write_stream = await self._exit_stack.enter_async_context(
            stdio_client(self._server_parameters)
        )
        self.session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(exc_type, exc_value, traceback)
        self.session = None
        self._exit_stack = None

    async def list_tools(self):
        if self.session is None:
            raise RuntimeError("MCP client is not connected")
        return await self.session.list_tools()

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, object],
    ) -> CallToolResult:
        if self.session is None:
            raise RuntimeError("MCP client is not connected")
        return await self.session.call_tool(name, arguments=dict(arguments))

    @staticmethod
    def text(result: CallToolResult) -> str:
        return "\n".join(
            item.text
            for item in result.content
            if isinstance(item, TextContent)
        )

    @staticmethod
    def has_embedded_resource(result: CallToolResult) -> bool:
        return any(isinstance(item, EmbeddedResource) for item in result.content)

    async def create_game(
        self,
        game_type: str,
        color: str = "white",
        difficulty: int = 5,
    ) -> GameSession:
        result = await self.call_tool(
            "createGame",
            {
                "type": game_type,
                "color": color,
                "difficulty": difficulty,
            },
        )
        response_text = self.text(result)
        game_match = re.search(r"Game ID: ([a-fA-F0-9-]+)", response_text)
        token_match = re.search(
            r"Player token: ([A-Za-z0-9_-]+)",
            response_text,
        )
        if game_match is None or token_match is None:
            raise RuntimeError(f"Could not parse createGame response:\n{response_text}")
        return GameSession(game_match.group(1), token_match.group(1), color)

    async def join_game(self, game_id: str) -> GameSession:
        result = await self.call_tool("joinGame", {"game_id": game_id})
        response_text = self.text(result)
        token_match = re.search(
            r"Player token: ([A-Za-z0-9_-]+)",
            response_text,
        )
        color_match = re.search(r"You are: (White|Black)", response_text)
        if token_match is None or color_match is None:
            raise RuntimeError(f"Could not parse joinGame response:\n{response_text}")
        return GameSession(
            game_id,
            token_match.group(1),
            color_match.group(1).lower(),
        )

    async def finish_turn(
        self,
        game: GameSession,
        move: str,
        claim_win: bool = False,
    ) -> CallToolResult:
        return await self.call_tool(
            "finishTurn",
            {
                "game_id": game.game_id,
                "move": move,
                "claim_win": claim_win,
                "player_token": game.player_token,
            },
        )

    async def wait_for_next_turn(self, game: GameSession) -> CallToolResult:
        return await self.call_tool(
            "waitForNextTurn",
            {
                "game_id": game.game_id,
                "player_token": game.player_token,
            },
        )
