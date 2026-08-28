---
name: mcp-chess-e2e
description: Run and extend end-to-end tests for the Chess MCP server through real stdio MCP clients and separate server processes. Use when testing MCP handshakes, chess game flows, AI turns, Human UI resources, or multi-session behavior.
---

# Chess MCP E2E Testing

## Purpose

Test the server through the MCP protocol rather than calling server functions
directly. Use `src.mcp_client.ChessMcpClient` as the reusable client.

## Standard command

Run the complete suite with:

```bash
uv run --extra dev pytest -q
```

Run only MCP scenario tests with:

```bash
uv run --extra dev pytest tests/test_mcp_client_scenarios.py -q
```

## Test isolation

- Give each test a unique temporary `CHESS_MCP_DB_PATH`.
- Set `BROWSER` to a nonexistent executable unless browser launching is being
  tested explicitly.
- Do not use the user's persistent game database.
- Let `ChessMcpClient` own the stdio and session lifecycle with `async with`.

## Required scenarios

Maintain coverage for:

1. MCP initialization and tool discovery.
2. Agent versus Computer with the agent as White.
3. Agent versus Computer with the agent as Black, including the initial AI move.
4. Agent versus Agent using two `ChessMcpClient` instances and the same
   temporary database path. Each client must run its own server process.
       5. Human game creation returning an embedded UI resource.
       6. State persistence after reconnecting to the same database.

## Scenario rules

       - Parse `game_id` from `createGame` and use the returned `GameSession` for
         subsequent calls.
- Call `joinGame` from the second client for Agent versus Agent scenarios.
- Assert both `result.isError` and meaningful state text where relevant.
- Prefer stable state assertions such as turn, FEN presence, and game-over
  status over exact prose wording.
- Use legal moves that are deterministic for the scenario; do not assume which
  move the AI selected unless the test explicitly controls randomness.

## Adding a scenario

1. Add the test to `tests/test_mcp_client_scenarios.py`.
2. Use a fresh `tmp_path` database.
3. Use separate client contexts when process isolation matters.
4. Verify both success and failure paths.
5. Run the focused test file, then the complete suite.

## Reporting

Report:

- the command executed;
- the scenario groups covered;
- the number of passed and failed tests;
- any environment or dependency limitation;
- warnings that remain after the run.
