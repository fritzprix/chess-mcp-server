# Chess MCP Server - Call Chain Diagrams

This document visualizes the tool call sequences for all game scenarios defined in the Chess MCP Server.

---

## Scenario 1: Agent (White) vs Computer

**Agent plays White, Computer plays Black**

```mermaid
sequenceDiagram
    participant Agent
    participant Server
    participant Computer

    Agent->>Server: createGame(type="computer", color="white")
    Server-->>Agent: Board State (Text)<br/>Next: finishTurn
    
    loop Game Loop
        Agent->>Server: finishTurn(move="e2e4")
        Server->>Server: Validate & Execute Move
        Server->>Computer: Trigger AI Move (async)
        Server-->>Agent: "Waiting for opponent..."<br/>Next: waitForNextTurn
        
        Computer->>Server: Execute AI Move
        
        Agent->>Server: waitForNextTurn()
        Server->>Server: Wait for move_event
        Server-->>Agent: Board State (Text)<br/>Next: finishTurn
    end
    
    Note over Agent,Computer: Loop continues until game over
```

**Call Chain:**
1. `createGame(type="computer", color="white")` → Board + "Next: finishTurn"
2. `finishTurn(move)` → "Waiting..." + "Next: waitForNextTurn"
3. `waitForNextTurn()` → Board + "Next: finishTurn"
4. Repeat steps 2-3 until game over

---

## Scenario 2: Agent (White) vs Human (Black)

**Agent plays White, Human plays Black via UI**

```mermaid
sequenceDiagram
    participant Agent
    participant Server
    participant Human

    Agent->>Server: createGame(type="human", color="white")
    Server-->>Agent: Board State (Text)<br/>Next: finishTurn
    
    loop Game Loop
        Agent->>Server: finishTurn(move="e2e4")
        Server->>Server: Validate & Execute Move
        Server-->>Agent: UI Resource (HTML)<br/>"Waiting for opponent..."<br/>Next: UI returned for human
        
        Note over Human: Human views UI and makes move
        Human->>Server: finishTurn(move="e7e5")
        Server->>Server: Validate & Execute Move
        Server-->>Agent: Board State (Text)<br/>Next: finishTurn
    end
    
    Note over Agent,Human: Loop continues until game over
```

**Call Chain:**
1. `createGame(type="human", color="white")` → Board + "Next: finishTurn"
2. `finishTurn(move)` → UI Resource + "Next: UI returned for human"
3. *Human moves via UI* → triggers `finishTurn(move)`
4. Server returns Board + "Next: finishTurn" to Agent
5. Repeat steps 2-4 until game over

---

## Scenario 3: Human (White) vs Agent (Black)

**Human plays White via UI, Agent plays Black**

```mermaid
sequenceDiagram
    participant Agent
    participant Server
    participant Human

    Agent->>Server: createGame(type="human", color="black")
    Server-->>Agent: UI Resource (HTML)<br/>"Waiting for Human..."<br/>Next: waitForNextTurn
    
    loop Game Loop
        Note over Human: Human views UI and makes move
        Human->>Server: finishTurn(move="e2e4")
        Server->>Server: Validate & Execute Move
        
        Agent->>Server: waitForNextTurn()
        Server-->>Agent: Board State (Text)<br/>Next: finishTurn
        
        Agent->>Server: finishTurn(move="e7e5")
        Server->>Server: Validate & Execute Move
        Server-->>Agent: UI Resource (HTML)<br/>"Waiting for opponent..."<br/>Next: UI returned for human
    end
    
    Note over Agent,Human: Loop continues until game over
```

**Call Chain:**
1. `createGame(type="human", color="black")` → UI Resource + "Next: waitForNextTurn"
2. *Human moves via UI* → triggers `finishTurn(move)`
3. `waitForNextTurn()` → Board + "Next: finishTurn"
4. `finishTurn(move)` → UI Resource + "Next: UI returned for human"
5. Repeat steps 2-4 until game over

---

## Scenario 4: Agent vs Agent (via joinGame)

**Two separate Agents play against each other**

```mermaid
sequenceDiagram
    participant Agent1
    participant Server
    participant Agent2
    participant Human

    Agent1->>Server: createGame(type="agent", color="white")
    Server-->>Agent1: Board State (Text)<br/>game_id="1234"<br/>Next: finishTurn
    
    Agent1->>Server: finishTurn(move="e2e4")
    Server-->>Agent1: "Waiting for opponent..."<br/>Next: waitForNextTurn
    
    Note over Human: Human copies join prompt from Dashboard
    Human->>Agent2: "Join game 1234"
    
    Agent2->>Server: joinGame(game_id="1234")
    Server-->>Agent2: Board State (Text)<br/>Next: Check turn, then finishTurn or waitForNextTurn
    
    loop Game Loop
        Agent2->>Server: finishTurn(move="e7e5")
        Server-->>Agent2: "Waiting for opponent..."<br/>Next: waitForNextTurn
        
        Agent1->>Server: waitForNextTurn()
        Server-->>Agent1: Board State (Text)<br/>Next: finishTurn
        
        Agent1->>Server: finishTurn(move="g1f3")
        Server-->>Agent1: "Waiting for opponent..."<br/>Next: waitForNextTurn
        
        Agent2->>Server: waitForNextTurn()
        Server-->>Agent2: Board State (Text)<br/>Next: finishTurn
    end
    
    Note over Agent1,Agent2: Loop continues until game over
```

**Call Chain (Agent 1 - White):**
1. `createGame(type="agent", color="white")` → Board + game_id + "Next: finishTurn"
2. `finishTurn(move)` → "Waiting..." + "Next: waitForNextTurn"
3. `waitForNextTurn()` → Board + "Next: finishTurn"
4. Repeat steps 2-3 until game over

**Call Chain (Agent 2 - Black):**
1. `joinGame(game_id)` → Board + "Next: Check turn, then finishTurn or waitForNextTurn"
2. `finishTurn(move)` → "Waiting..." + "Next: waitForNextTurn"
3. `waitForNextTurn()` → Board + "Next: finishTurn"
4. Repeat steps 2-3 until game over

---

## Summary: Tool Call Patterns

### Pattern 1: Agent Moves First (White)
```
createGame → finishTurn → waitForNextTurn → finishTurn → ...
```

### Pattern 2: Opponent Moves First (Black)
```
createGame → waitForNextTurn → finishTurn → waitForNextTurn → ...
```

### Pattern 3: Agent vs Human (Agent is White)
```
createGame → finishTurn → [Human moves] → finishTurn → ...
```
*Note: No `waitForNextTurn` needed - human moves trigger direct response*

### Pattern 4: Agent vs Human (Agent is Black)
```
createGame → [Human moves] → waitForNextTurn → finishTurn → [Human moves] → ...
```

### Pattern 5: Agent vs Agent
```
Agent 1: createGame → finishTurn → waitForNextTurn → finishTurn → ...
Agent 2: joinGame → finishTurn → waitForNextTurn → finishTurn → ...
```

---

## Key Observations

1. **`waitForNextTurn` is only needed for non-human opponents** (computer or agent)
   - Human moves are handled via UI and don't require polling

2. **UI Resources are only returned when it's the human's turn**
   - Agent (White) vs Human: UI returned after agent's `finishTurn`
   - Agent (Black) vs Human: UI returned at `createGame` and after agent's `finishTurn`

3. **Computer moves are automatic**
   - Triggered asynchronously after agent's `finishTurn`
   - Agent must call `waitForNextTurn` to get the result

4. **All paths have explicit next action guidance**
   - Every response tells the agent exactly which tool to call next
   - No ambiguity in the flow

5. **Game over terminates the loop**
   - Both `finishTurn` and `waitForNextTurn` detect game over
   - Response includes "No further actions needed"
