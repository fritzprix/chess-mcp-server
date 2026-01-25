# Best Practices for MCP Tool Implementation

This guide synthesizes the lessons learned from building the Chess MCP Server, focusing on creating **Agentic** tools that are robust, self-correcting, and easy to use.

## 1. Explicit Next Action Guidance
Agents often get "stuck" deciding what to do after a tool call returns. Always provide a clear "Next Action" hint in your tool's string return value.

*   **Bad**: `Return: "Move accepted."`
*   **Good**: `Return: "Move accepted. Next action: Call waitForNextTurn(game_id) to wait for opponent."`

**Pattern**:
```python
return f"{result}\n\nNext Action: Call `next_tool_name(...)` to [achieve goal]."
```

## 2. Actionable Error Messages
When an Agent makes a mistake (e.g., illegal move, invalid format), do not just error out. usage the exception to **teach** the Agent how to fix it.

*   **Bad**: `ValueError("Invalid move")`
*   **Good**: `ValueError("Illegal move 'e2e9'. The e-file only goes to 8. Sample legal moves: e2e4, e2e3.")`

**Key Elements**:
1.  **What happened**: "Invalid move"
2.  **Why**: "e-file only goes to 8"
3.  **How to fix**: "Sample legal moves: ..."

## 3. State Awareness in Text
Agents do not have memory of previous tool calls' return values in the way humans do. Every response should re-state critical context if it might have changed.

For the Chess Server, `waitForNextTurn` returns:
```markdown
[Board Visual]

**Turn**: White to move
**FEN**: rnbq...
```
Explicitly stating "Turn: White" prevents the Agent from hallucinating whose turn it is, even if it could theoretically deduce it from the board.

## 4. UI/Human Acknowledgment
If your tool involves a Human-in-the-Loop (like `showUi=True`), the UI must explicitly tell the *Human* who they are.

*   **Display User Identity**: "You are playing as: **White**"
*   **Orientation**: Flip the board/visuals so the User's perspective is natural (e.g., Human playing Black sees Black at the bottom).

## 5. Defensive "Long Polling"
For tools that wait for an external event (like `waitForNextTurn`), implement a timeout loop rather than returning immediately if the state hasn't changed.

*   **Logic**:
    1.  Check current state. Is it already the Agent's turn? -> Return immediately.
    2.  If not, wait (async) for a "State Changed" event (max 30s).
    3.  If timeout, return a "No change, try again" message so the Agent knows to retry rather than assume failure.

## 6. Type Safety with Pydantic
Use Pydantic models for all tool arguments. This gives the Agent distinct schema structures to reason about.

```python
class GameConfig(BaseModel):
    # Enums constrain the Agent's choices, reducing errors
    color: Literal["white", "black"] = Field("white", description="...")
```
