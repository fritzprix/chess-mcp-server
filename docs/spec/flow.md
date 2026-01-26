# Chess MCP Game Flow Scenarios

This document outlines the expected flow of information between the Agent, the MCP Server, and the User (via UI) for different game configurations.

## Scenario 1: Agent (White) vs Computer
**Goal**: Agent plays White against Stockfish (AI).

1.  **Agent**: Calls `createGame(type="computer", color="white")`.
2.  **Server**: Returns **Board State (Text)**.
    *   *Next Action*: `finishTurn`
3.  **Agent**: Decides move (e.g., "e2e4") and calls `finishTurn(move="e2e4")`.
4.  **Server**:
    *   Validates move.
    *   Updates board (White moved).
    *   Triggers Computer (Black) move immediately (or async).
    *   **Returns**: "Wait for computer..." (Text).
    *   *Next Action*: `waitForNextTurn`
5.  **Agent**: Calls `waitForNextTurn()`.
    *   *Blocks until Computer moves.*
6.  **Server**: Returns **Board State (Text)** (after Computer moved).
    *   *Next Action*: `finishTurn`
7.  **(Loop repeats from Step 3)**

---

## Scenario 2: Agent (White) vs Human (Black)
**Goal**: Agent plays White against a Human (via Browser UI).

1.  **Agent**: Calls `createGame(type="agent", color="white", showUi=true)`.
2.  **Server**: Returns **Board State (Text)**.
    *   *Note*: No UI returned. Agent is White and moves first.
    *   *Next Action*: `finishTurn`
3.  **Agent**: Decides move (e.g., "e2e4") and calls `finishTurn(move="e2e4")`.
4.  **Server**:
    *   Validates move.
    *   **Returns**: **UI Resource (HTML)** + "Waiting for opponent...".
    *   *Mechanism*: This UI return allows the Human to take over in the MCP Client.
    *   *Next Action*: None (Agent yields).
5.  **Human (MCP Client)**:
    *   Uses the returned UI Resource to view board and move.
    *   Moves ("e7e5") -> Triggers `finishTurn(move="e7e5")`.
6.  **Server**:
    *   Processes Human move.
    *   **Returns (to Agent)**: **Board State (Text)**.
    *   *Note*: Does NOT return UI again (it is now Agent's turn).
    *   *Next Action*: `finishTurn`
7.  **(Loop repeats from Step 3)**

---

## Scenario 3: Human (White) vs Agent (Black)
**Goal**: Human plays White against Agent.

1.  **Agent**: Calls `createGame(type="agent", color="black", showUi=true)`.
2.  **Server**: Checks configuration.
    *   Agent is Black -> Human is White.
    *   **Returns**: **UI Resource (HTML)** + "Game Created. Waiting for Human (White) to move.".
    *   *Next Action*: None (Agent yields).
3.  **Human (Browser)**:
    *   Moves ("e2e4") -> Triggers `finishTurn(move="e2e4")`.
4.  **Server**:
    *   Processes move.
    *   **Returns (to Agent)**: **Board State (Text)**.
    *   *Next Action*: `finishTurn`
5.  **Agent**:
    *   Decides move ("e7e5") -> Calls `finishTurn(move="e7e5")`.
6.  **Server**:
    *   Validates move.
    *   **Returns**: Text "Waiting for opponent..." (No UI needed again if already active/persisting, or if specifically requested not to spam UI).
    *   *Next Action*: None (Agent yields).
7.  **(Loop repeats from Step 3)**

---

## Scenario 4: Agent vs Agent (via `joinGame`)
**Goal**: Two separate Agents play against each other using `joinGame`.

1.  **Agent 1 (Host)**: Calls `createGame(type="agent", color="white", showUi=false)`.
    *   **Server Returns**: **Board State (Text)** + `game_id` (e.g., "1234").
    *   *Next Action*: `finishTurn`.
2.  **Agent 1**: Calls `finishTurn(move="e2e4")`.
    *   **Server Returns**: "Move accepted. Waiting for opponent."
    *   *Next Action*: `waitForNextTurn`.
3.  **Human (Intermediary)**:
    *   Accesses the Web UI (Dashboard).
    *   Uses the "Copy Join Prompt" feature (button) to get the instruction (e.g., "Join game 1234").
    *   Pastes this prompt to Agent 2.
4.  **Agent 2 (Joiner)**: Calls `joinGame(game_id="1234")`.
    *   **Server Returns**: **Board State (Text)** (Current state after e2e4).
    *   *Next Action*: `finishTurn`.
5.  **Agent 2**: Calls `finishTurn(move="e7e5")`.
    *   **Server Returns**: "Move accepted. Waiting for opponent."
    *   *Next Action*: `waitForNextTurn`.
6.  **Agent 1**: `waitForNextTurn()` detects move.
    *   **Server Returns**: **Board State (Text)**.
    *   *Next Action*: `finishTurn`.
7.  **(Loop continues: Agent 1 moves -> Wait -> Agent 2 Detects -> Moves -> Wait)**    
        
        

