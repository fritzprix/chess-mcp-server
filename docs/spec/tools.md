# MCP Chess Game Tools Specification

This document defines the tools exposed by the Chess MCP Server.

## Data Structures

```typescript
type PlayerType = "computer" | "agent";

interface GameConfig {
  type: PlayerType;
  /**
   * If true, the server will return an HTML UI representation of the board
   * in waitForNextTurn. Required for human players.
   */
  showUi?: boolean; 
  /**
   * Difficulty level (1-20) if playing against computer.
   */
  difficulty?: number; 
}
```

## Tools

### 1. `createGame`

Initializes a new chess game session.

- **Arguments**:
  - `config` (GameConfig): Configuration for the new game.
- **Returns**: Text confirmation with Game ID.

**Example Response**:
```markdown
Game Created Successfully!
- Game ID: 8f4b23a1
- White: Agent (You)
- Black: Computer (Level 5)

Next action: Call `waitForNextTurn(game_id="8f4b23a1")` to start.
```

---

### 2. `waitForNextTurn`

Blocks execution until it is the Agent's turn to move, or a timeout occurs.
This tool implements a "Long Polling" mechanism to keep the Client/Agent synchronized with the game state.

- **Arguments**:
  - `game_id` (string): The ID of the active game.
- **Behavior**:
  - **Blocking**: The tool call will BLOCK for up to **30 seconds**.
  - **Return Condition 1 (Activity)**: If the opponent completes their move within the window, the tool returns immediately with the new board state.
  - **Return Condition 2 (Timeout)**: If 30 seconds elapse without a move, the tool returns a specific "Timeout" message.
- **Returns**:
  - **Case A: New State Available (It is now YOUR turn)**
    - Text: Markdown representation of the board (ASCII/Table).
    - UI Resource (if `showUi=true`): Embedded HTML/JS board allowing user interaction.
  - **Case B: Game Over (Checkmate/Draw)**
    - Text: Game result (e.g., "Game Over: White wins by Checkmate").
  - **Case C: Timeout**
    - Text: "Timeout: No move received yet. Please call this tool again immediately."

**Markdown Board Example**:
```markdown
| Rank | a | b | c | d | e | f | g | h |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **8** | ♜ | ♞ | ♝ | ♛ | ♚ | ♝ | ♞ | ♜ |
...
```

---

### 3. `finishTurn`

Submits a move to the game server. This tool is capable of handling moves from ANY source (Agent logic or User UI interaction).

- **Arguments**:
  - `game_id` (string): The ID of the active game.
  - `move` (string): The move in UCI format (e.g., "e2e4", "a7a8q").
  - `claim_win` (boolean, optional): **[NEW]** Set to `true` to explicit claim a Checkmate/Win with this move.
- **Validation Actions**:
  1.  **Existence**: Checks if `game_id` exists.
  2.  **Turn Order**: Checks if it is currently the turn of the entity attempting to move.
  3.  **Legality**: Checks if the `move` is legal on the current board.
  4.  **Claim Verification**: If `claim_win` is true, checks if the resulting board state is indeed Checkmate.
- **Returns**:
  - **Success**: "Move acceptable."
  - **Success (Game Over)**: "Move accepted. Game Over: [Result]."
  - **Error - Invalid Move**: "Invalid move: [Reason]"
  - **Error - Failed Claim**: "Move rejected: You claimed Checkmate, but this move does not result in Checkmate."

---

## UI Logic (For `showUi: true`)

When `waitForNextTurn` returns the UI Resource, the HTML payload must support the Explicit Checkmate Claim workflow.

**UI Elements**:
1.  **Board**: Interactive drag-and-drop.
2.  **Move Input**: Text field for UCI (fallback).
3.  **"Claim Checkmate" Checkbox**: Allows the user to assert this is a winning move.
4.  **Confirm Button**: Sends the move.

**JavaScript Action**:
```javascript
// On 'Confirm' Click
const move = getMoveFromBoard(); // e.g. "e2e4"
const isWinClaimed = document.getElementById('chkWaitMate').checked;

window.parent.postMessage({
  type: 'action',
  action: 'finishTurn', 
  payload: { 
    game_id: CURRENT_GAME_ID, 
    move: move,
    claim_win: isWinClaimed // Sent to finishTurn tool
  } 
}, '*');
```

The MCP Host intercepts this `postMessage` and calls the `finishTurn` tool with the provided arguments.