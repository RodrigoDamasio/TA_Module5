# Lab 05: Multi-Agent Orchestration

## Objective

Build a quick multi-agent system using the supervisor pattern.

**Time Allotted:** 30 minutes

## Learning Goals

- Implement supervisor pattern for agent coordination
- Build specialized worker agents
- Orchestrate multi-step workflows

## What You'll Build

A mini research assistant with:

- **Supervisor Agent:** Coordinates workers and synthesizes results
- **Researcher Agent:** Finds and summarizes information
- **Writer Agent:** Produces polished output

```
┌─────────────────────────────────────────────────────────────┐
│                  Multi-Agent Architecture                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                    ┌─────────────┐                          │
│                    │ SUPERVISOR  │                          │
│                    │    AGENT    │                          │
│                    └──────┬──────┘                          │
│                           │                                 │
│              ┌────────────┼────────────┐                    │
│              │            │            │                    │
│              ▼            ▼            ▼                    │
│       ┌──────────┐ ┌──────────┐ ┌──────────┐                │
│       │RESEARCHER│ │  WRITER  │ │ REVIEWER │                │
│       │  AGENT   │ │  AGENT   │ │  AGENT   │                │
│       └──────────┘ └──────────┘ └──────────┘                │
│                                                             │
│   Flow:                                                     │
│   1. Supervisor receives task                               │
│   2. Delegates research to Researcher                       │
│   3. Sends research to Writer for polishing                 │
│   4. Optionally sends to Reviewer                           │
│   5. Supervisor synthesizes final output                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Requirements

### Core Functionality

- `POST /run` endpoint accepting `{"task": "...", "max_iterations": 5}`
- Supervisor Agent that:
  - Parses task and decides which worker to delegate to
  - Uses `DELEGATE`/`TASK` format for delegation
  - Uses `FINAL` format for completion
  - Synthesizes results from all workers
- Worker Agents (at least 2):
  - Each with specialized system prompt
  - Accept task + context, return result
- Iteration limit with forced completion
- Health check endpoint

### Frontend Requirements

- Chat-like web interface to submit research tasks
- Real-time agent activity feed showing which agent is working
- Conversation history showing Supervisor decisions and Worker results
- Final output panel with formatted result
- Responsive design

## Language Choice

| Language   | Run Command                 |
|------------|-----------------------------|
| Python     | `uvicorn main:app --reload` |
| TypeScript | `npm run dev`               |

## Deliverables

- [ ] Working multi-agent system
- [ ] Supervisor + at least 2 worker agents
- [ ] Tested end-to-end workflow
- [ ] Web frontend with chat interface and agent activity visualization
- [ ] Application deployed to Vercel/Railway/Render (provide URL)

## Extension Ideas (Post-Training)

- **Parallel Workers:** Run independent workers in parallel
- **Human Approval:** Add human-in-the-loop for important decisions
- **Memory:** Add persistent memory across tasks
- **More Workers:** Add specialized agents (Editor, Fact-Checker, etc.)
