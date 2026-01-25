# MCP Tools Specification Feasibility Analysis

## 1. Overview
This document analyzes the feasibility of the tools defined in `docs/spec/tools.md` based on the `docs/mcp_reference_en.md` standard.

**Conclusion:** The proposed specification is **FEASIBLE**.
**Updates:**
- Generic `finishTurn` is recommended.
- `waitForNextTurn` with 30s long-polling is feasible.
- **Checkmate Claiming**: Explicit checkmate acknowledgment by the user is feasible and supported.
- **Web Dashboard**: Sidecar web server with auto-launch is feasible.

## 2. Detailed Verification

| Feature spec | MCP Reference Component | Feasibility | Notes |
| :--- | :--- | :--- | :--- |
| **Tool: `createGame`** | Section 2.4 (Tools) | ✅ Supported | Standard tool definition. Returns text. |
| **Tool: `waitForNextTurn`** | Section 2.4 (Tools) | ✅ Supported | Standard tool definition. Returns text + resource. |
| **Tool: `finishTurn`** | Section 2.4 (Tools) | ✅ Supported | Generic submission of moves. Replaces `finishUserTurn`. |
| **Text Rendering** | N/A (Client Rendering) | ✅ Supported | Markdown tables are standard in LLM responses. |
| **UI Resource** | Section 3.1 & 3.2 | ✅ Supported | `text/html` is a valid `UIResource` MIME type (Strategy 1). |
| **UI Interaction (Move)** | Section 3.3 (UI Actions) | ✅ Supported* | Requires Host to handle `postMessage` and strict `onUIAction` loop. |

## 3. Implementation Details & Considerations

### 3.1 UI Resource Implementation
The specification calls for returning an HTML board when `showUi` is true.
According to Reference Section 3.2 (Strategy 1):
- Server returns: simple HTML string.
- Host behavior: Injects into sandboxed iframe.
- **Feasible**: Yes, the Python `show_dashboard` example (Reference Section 4.2) directly demonstrates this pattern using `text/html`.

### 3.2 Bi-directional Interaction (The "User Move")
The spec mentions: "User... selects Confirm... user's move is sent to server... usage choice is `finishUserTurn`... via MCP UI ui action".

**Mechanism:**
1.  **HTML Logic**: The embedded HTML board must contain JavaScript to capture clicks and send a message.
    ```javascript
    // Inside the HTML returned by waitForNextTurn
    window.parent.postMessage({
      type: 'action',
      action: 'finishTurn', // GENERIC NAME RECOMMENDED
      payload: { from: 'e2', to: 'e4' } 
    }, '*');
    ```
2.  **Host Handling**: The MCP Host (e.g., Claude Desktop, IDE) receives this event.
3.  **Loopback**: The Host must route this action to a tool call.
    - *Note*: The MCP reference Section 3.3 says "The host then cycles this back by calling MCP tools".
    - You will likely need to expose `finishUserTurn` as an MCP Tool so the host (or the Agent reacting to the UI event) can call it.

### 3.3 The `waitForNextTurn` Blocking Issue
One logical ambiguity in the spec is the behavior of `waitForNextTurn` when it is the **Human's** turn.
- If the LLM calls `waitForNextTurn`, and it is the Human's turn, the tool should likely:
    1.  Return the board state immediately with a status "Waiting for User".
    2.  The LLM should then perhaps yield or wait?
    3.  **Recommended Pattern**: The `waitForNextTurn` tool serves as a "Refresh/Poll" mechanism. The LLM sees the state. If it's human turn, LLM does nothing (or just outputs "Waiting for human move..."). When Human moves (via UI -> `finishUserTurn`), the state updates. The LLM might be re-triggered or manually check again.

## 4. Analysis: `finishTurn` vs `finishUserTurn`
The user questioned if a generic `finishTurn` is sufficient for both scenarios (Agent move vs User move).

**Recommendation: Use `finishTurn` for ALL moves.**

### Reasons:
1.  **Protocol Simplicity**: The server logic is "Execute Move X on Game Y". The mechanics of *who* originated the move (Agent thinking process vs User UI click) are transport details.
2.  **State-Driven Validation**: The Server already knows whose turn it is.
    *   If requests `finishTurn` and it is **Agent's Turn**: Accepted.
    *   If requests `finishTurn` and it is **User's Turn**: Accepted (assuming the UI triggered it).
    *   *Security Note*: Strictly speaking, if the Agent (LLM) hallucinates and calls `finishTurn` during the User's turn, the server MUST return an error ("Not your turn"). This state check is required regardless of the tool name.
3.  **Unified Schema**:
    ```typescript
    finishTurn(game_id: string, move: string)
    ```
    This single signature covers both cases.

### Revised Flow with `finishTurn`:
1.  **Agent Turn**: LLM thinks -> Calls `finishTurn(game_id, move)`. Server updates state.
2.  **User Turn**:
    *   LLM Calls `waitForNextTurn`.
    *   Server returns UI.
    *   User interacts with UI -> `postMessage({ action: 'finishTurn', ... })`.
    *   Host receives message -> Calls `finishTurn(game_id, move)`.
    *   Server updates state.

## 5. Analysis: `waitForNextTurn` Blocking Strategy
The proposed strategy is:
- **Blocking**: 30 seconds wait for opponent move.
- **Return Condition 1 (Activity)**: Opponent moves -> Return State Immediately.
- **Return Condition 2 (Timeout)**: 30s elapsed -> Return "Timeout, try again" message.

**Feasibility: ✅ Confirmed**

### Considerations:
1.  **Host Timeout**: Most MCP Clients (Host applications) set a timeout for tool calls.
    - *Typical Default*: Often 60s or more.
    - *Risk*: If the Host has a very short timeout (e.g., 10s), this call will fail with a Protocol Error before the server returns the custom "Timeout" message.
    - *Mitigation*: 30 seconds is generally a safe lower bound. It allows for a "Long Poll" pattern without triggering aggressive read timeouts.
2.  **Server Implementation**:
    - Must use asynchronous sleep (`await asyncio.sleep(0.1)` or `threading.Event`).
    - Do NOT use `time.sleep(30)` in a single-threaded blocking server, as it will freeze the entire server for all users/requests.
    - *Recommendation*: Use `async def` and event loops (FastMCP supports this natively).
3.  **LLM Loop**:
    - The LLM must be instructed (via the System Prompt or Tool Description) that receiving a "Timeout" is **normal** and it should simply call the tool again. Without this, the LLM might interpret the timeout as a failure and stop or hallucinate complications.

**Revised Tool Description Suggestion:**
> "Waits for the opponent to move. Blocks for up to 30 seconds. If the opponent moves, returns the new board state. If no move occurs within 30 seconds, returns a timeout message. You should immediately call this tool again if you receive a timeout."

## 6. Analysis: Checkmate Acknowledgement
The user requested that the user must "explicitly decide" whether a move is checkmate.

**Feasibility: ✅ Confirmed**

To support this:
1.  **Protocol**: Update `finishTurn` to accept `claim: string` (values: `null`, `'checkmate'`, `'draw'`).
2.  **Validation**:
    - If `claim='checkmate'` is sent, the server MUST verify `board.is_checkmate()` AFTER the move.
    - If valid -> Win acknowledged.
    - If invalid -> Return error "Accusation failed: Not checkmate".
3.  **UI**: The HTML Board requires an interactive element (e.g., specific "Move & Claim Checkmate" button or a toggle).

**Modified Schema**:
```typescript
finishTurn(
  game_id: string, 
  move: string, 
  claim_win?: boolean // if true, asserts this move ends the game
)
```

**Recommendation for Spec**: Include `claim_win` as an optional parameter to support this "Explicit Decision" mechanic.

## 7. Analysis: Web Dashboard & Sidecar Server
**Use Case**: When the MCP server starts, it should satisfy "start web server + open browser" to show a game list.

**Feasibility: ✅ Confirmed (with considerations)**

### Architecture
- **Dual Interface**:
    1.  **MCP Interface**: Stdio/SSE handling JSON-RPC.
    2.  **HTTP Interface**: Sidecar web server (e.g., Flask/FastAPI/Starlette) running on localhost (random or fixed port).
- **Execution**: The MCP server entry point must launch the HTTP server background thread/task on startup (`lifespan` event or `__main__`).

### Mechanism
1.  **Startup**:
    - Initialize `FastMCP` (or equivalent).
    - Start HTTP Server (e.g. `uvicorn.run` in a thread).
    - Get Port (e.g., `8080`).
2.  **Browser Launch**:
    - Use Python `webbrowser` module: `webbrowser.open("http://localhost:8080")`.
    - *Note*: This works well on local machines (macOS/Windows/Linux). It may fail silently in headless environments (SSH/Cloud), which is acceptable.

### UX Consideration
- **Auto-Open**: If the server crashes/restarts frequently, the browser popping up repeatedly can be annoying.
- **Mitigation**: Add a logic to only open if not already "running" or check a flag/env var `MCP_DISABLE_BROWSER=1`.

### Integration with Game State
- The Game State manager must be a singleton shared between the MCP Tools context and the HTTP Server endpoints.
- **Endpoints**:
    - `GET /`: HTML Dashboard showing list of active games.
    - `GET /api/games`: JSON list.
    - `GET /game/{id}`: View specific game board (spectator mode).
