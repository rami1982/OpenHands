# Autonomous Agent Orchestrator Flow

This document provides a comprehensive overview of how the Autonomous Coding Agent Orchestrator works, from startup to task completion.

---

## Table of Contents

1. [Overview](#overview)
2. [System Startup Flow](#system-startup-flow)
3. [Task Processing Flow](#task-processing-flow)
4. [Task State Transitions](#task-state-transitions)
5. [Error Handling Flow](#error-handling-flow)
6. [Budget Management Flow](#budget-management-flow)
7. [Persistence and Recovery](#persistence-and-recovery)
8. [Complete Flow Diagram](#complete-flow-diagram)

---

## Overview

The orchestrator operates as a continuous daemon that:
1. Loads tasks from a queue
2. Executes each task using OpenHands agent
3. Manages API budgets and rate limits
4. Commits successful work to Git
5. Handles errors gracefully
6. Persists state for crash recovery

---

## System Startup Flow

```
┌─────────────────────────────────────────────────────────────┐
│ 1. START: python run_orchestrator.py                       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Load Configuration                                       │
│    • Read config.autonomous.toml                            │
│    • Parse task_source, git settings, budget settings       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. Initialize Core Components                              │
│    • OpenHandsConfig - Main OpenHands configuration         │
│    • LLMRegistry - LLM provider registry                    │
│    • TokenCostManager - Budget and rate limit manager       │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Wrap LLM Client                                          │
│    • Get default LLM from registry                          │
│    • Wrap with TokenCostManager for budget tracking         │
│    • Create Agent with wrapped LLM                          │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. Initialize Task Queue                                   │
│    • Load TaskQueue from tasks.json                         │
│    • If empty: Parse markdown files from tasks/             │
│    • Add parsed tasks to queue                              │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 6. Enter Main Orchestration Loop                           │
│    (See Task Processing Flow below)                         │
└─────────────────────────────────────────────────────────────┘
```

### Code Reference

**File**: `run_orchestrator.py:25-61`

```python
async def main():
    # 1. Load Configuration
    with open("config.autonomous.toml", "r") as f:
        orchestrator_config = toml.load(f)

    # 2-4. Initialize Components and Wrap LLM
    config = OpenHandsConfig()
    llm_registry = LLMRegistry(config)
    cost_manager = TokenCostManager(orchestrator_config.get("cost_management"))

    default_llm = llm_registry.get_llm()
    budget_aware_llm = cost_manager.get_wrapped_llm_client(default_llm)
    agent = Agent(llm=budget_aware_llm, config=agent_config)

    # 5. Initialize Task Queue
    task_queue = TaskQueue(queue_file="tasks.json")
    if not task_queue.get_all_tasks():
        tasks = parse_markdown_files(md_path)
        for task in tasks:
            task_queue.add_task(task)

    # 6. Main Loop
    while True:
        task = task_queue.get_next_task()
        if not task:
            break
        # Process task...
```

---

## Task Processing Flow

```
┌─────────────────────────────────────────────────────────────┐
│ GET NEXT TASK                                               │
│ task_queue.get_next_task()                                  │
│ • Returns first task with status = "pending"                │
│ • Returns None if no pending tasks                          │
└─────────────────────────────────────────────────────────────┘
                           ↓
                    ┌──────┴──────┐
                    │   Task?     │
                    └──────┬──────┘
                      No ↙    ↘ Yes
              ┌─────────┐    ┌─────────────────────────────┐
              │  EXIT   │    │ UPDATE STATUS: in_progress  │
              │ SUCCESS │    │ Log: "Starting task..."     │
              └─────────┘    └─────────────────────────────┘
                                          ↓
                           ┌──────────────────────────────┐
                           │ CREATE GIT WORKSPACE         │
                           │ • Initialize GitWorkspace()  │
                           │ • Create branch:             │
                           │   agent/task-{task_id}       │
                           └──────────────────────────────┘
                                          ↓
                           ┌──────────────────────────────┐
                           │ INITIALIZE SESSION           │
                           │ • session_id = task_id       │
                           │ • LocalFileStore             │
                           │ • ConversationStats          │
                           │ • Create AgentSession        │
                           └──────────────────────────────┘
                                          ↓
                           ┌──────────────────────────────┐
                           │ START AGENT SESSION          │
                           │ • Pass task description as   │
                           │   initial MessageAction      │
                           │ • Agent begins work          │
                           │ • Budget-wrapped LLM used    │
                           └──────────────────────────────┘
                                          ↓
                           ┌──────────────────────────────┐
                           │ POLL FOR COMPLETION          │
                           │ • Check every 5 seconds      │
                           │ • Wait for agent state:      │
                           │   finished/error/stopped     │
                           └──────────────────────────────┘
                                          ↓
                    ┌──────────────────────────────────┐
                    │ CHECK FINAL STATE                │
                    └──────────────────────────────────┘
                              ↓
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
┌───────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ "finished"    │   │ "error"/"stopped"│   │ Exception raised │
└───────────────┘   └──────────────────┘   └──────────────────┘
        ↓                     ↓                     ↓
┌───────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ SUCCESS PATH  │   │  FAILURE PATH    │   │  ERROR PATH      │
│ (see below)   │   │  (see below)     │   │  (see below)     │
└───────────────┘   └──────────────────┘   └──────────────────┘
```

### Success Path

```
┌─────────────────────────────────────────────────────────────┐
│ COMMIT CHANGES                                              │
│ • workspace.add_all_and_commit()                            │
│ • Message: "feat: complete task {id}\n\n{description}"      │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ UPDATE TASK STATUS                                          │
│ • task_queue.update_task_status(task.id, "completed")       │
│ • Persisted to tasks.json                                   │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ CLEANUP                                                     │
│ • Close AgentSession                                        │
│ • Checkout original Git branch                             │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ NEXT TASK                                                   │
│ • Continue to next pending task in queue                    │
└─────────────────────────────────────────────────────────────┘
```

### Failure Path

```
┌─────────────────────────────────────────────────────────────┐
│ LOG ERROR                                                   │
│ • logger.error("An error occurred...")                      │
│ • Include full stack trace                                  │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ UPDATE TASK STATUS                                          │
│ • task_queue.update_task_status(task.id, "failed")          │
│ • Task will NOT be retried automatically                    │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ RESET WORKSPACE                                             │
│ • workspace.reset_branch()                                  │
│ • Discard all changes made during failed task               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ CLEANUP                                                     │
│ • Close AgentSession                                        │
│ • Checkout original Git branch                             │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ NEXT TASK                                                   │
│ • Continue to next pending task (skip failed one)           │
└─────────────────────────────────────────────────────────────┘
```

### Code Reference

**File**: `run_orchestrator.py:62-145`

---

## Task State Transitions

```
                    ┌─────────────────┐
                    │  Task Created   │
                    │ (from .md file) │
                    └────────┬────────┘
                             ↓
                    ┌────────────────┐
                    │   "pending"    │◄──────────────┐
                    └────────┬───────┘               │
                             │                       │
                 get_next_task() picks it           │
                             ↓                       │
                    ┌────────────────┐               │
                    │ "in_progress"  │               │
                    └────────┬───────┘               │
                             │                       │
                    ┌────────┴────────┐              │
                    │                 │              │
            ┌───────▼──────┐  ┌──────▼────────┐    │
            │  "completed"  │  │   "failed"    │    │
            │  (SUCCESS)    │  │  (ERROR)      │    │
            └───────────────┘  └───────────────┘    │
                                                     │
                    Budget/Rate Limit Hit ───────────┘
                    (Re-queue as "pending")
```

### State Descriptions

| State | Meaning | Selected by get_next_task()? | Auto-retry? |
|-------|---------|------------------------------|-------------|
| **pending** | Waiting to be executed | ✅ YES | N/A |
| **in_progress** | Currently executing | ❌ NO | ❌ NO (manual reset needed) |
| **completed** | Successfully finished | ❌ NO | ❌ NO (never re-run) |
| **failed** | Execution failed | ❌ NO | ❌ NO (manual reset needed) |

### Special Cases

**Budget/Rate Limit Exhaustion:**
- Task status changed from `in_progress` back to `pending`
- Orchestrator sleeps until budget resets
- Task will be retried after sleep

**System Crash/Reboot:**
- Tasks in `in_progress` state remain stuck
- Require manual intervention to reset to `pending`
- This prevents duplicate work if task partially completed

### Code Reference

**File**: `autonomous_agent/task_queue.py:6-7`
```python
VALID_STATUSES = ["pending", "in_progress", "completed", "failed"]
```

**File**: `run_orchestrator.py:114` (completed)
**File**: `run_orchestrator.py:120` (re-queue on budget limit)
**File**: `run_orchestrator.py:135` (failed)

---

## Error Handling Flow

```
                    ┌─────────────────────┐
                    │  Exception Raised   │
                    └──────────┬──────────┘
                               ↓
                    ┌──────────────────────┐
                    │  Exception Type?     │
                    └──────────┬───────────┘
                               ↓
      ┌────────────────────────┼────────────────────────┐
      ↓                        ↓                        ↓
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│BudgetExhausted  │  │ExtendedRateLimit │  │ Other Exception  │
│Error            │  │Error             │  │                  │
└─────────┬───────┘  └─────────┬────────┘  └────────┬─────────┘
          ↓                    ↓                     ↓
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Re-queue task   │  │ Re-queue task    │  │ Mark as "failed" │
│ as "pending"    │  │ as "pending"     │  │                  │
└─────────┬───────┘  └─────────┬────────┘  └────────┬─────────┘
          ↓                    ↓                     ↓
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Calculate sleep │  │ Use configured   │  │ Log error with   │
│ until budget    │  │ cooldown period  │  │ stack trace      │
│ reset time      │  │ (default: 1hr)   │  │                  │
└─────────┬───────┘  └─────────┬────────┘  └────────┬─────────┘
          ↓                    ↓                     ↓
┌─────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Sleep until     │  │ Sleep for        │  │ Reset Git branch │
│ reset time      │  │ cooldown period  │  │ (discard changes)│
└─────────┬───────┘  └─────────┬────────┘  └────────┬─────────┘
          ↓                    ↓                     ↓
          └──────────┬─────────┘                     │
                     ↓                               ↓
          ┌──────────────────┐           ┌──────────────────┐
          │ Continue to next │           │ Continue to next │
          │ task (retry this)│           │ task (skip this) │
          └──────────────────┘           └──────────────────┘
```

### Error Recovery Strategies

#### 1. Budget Exhausted Error
```python
# Exception raised when token budget is exceeded
try:
    cost_manager.check_and_record_usage(tokens)
except BudgetExhaustedError as e:
    # Get reset time from exception
    sleep_duration = (e.reset_time - datetime.utcnow()).total_seconds()
    time.sleep(sleep_duration)
    # Retry the same task
```

#### 2. Extended Rate Limit Error
```python
# Exception raised after retry attempts exhausted
try:
    llm.completion(...)
except ExtendedRateLimitError:
    # Cool down for configured period
    cooldown = config.get("cooldown_period_on_extended_rate_limit", 3600)
    time.sleep(cooldown)
    # Retry the same task
```

#### 3. Other Exceptions
```python
# Any other exception
except Exception as e:
    logger.error(f"Task failed: {e}", exc_info=True)
    task_queue.update_task_status(task.id, "failed")
    workspace.reset_branch()
    # Skip to next task
```

### Code Reference

**File**: `run_orchestrator.py:118-145`

---

## Budget Management Flow

```
┌─────────────────────────────────────────────────────────────┐
│ LLM CALL INITIATED                                          │
│ agent.run() → llm.completion(messages)                      │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ WRAPPED COMPLETION (TokenCostManager)                       │
│ • Estimate prompt tokens: len(messages) / 4                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ PROACTIVE BUDGET CHECK                                      │
│ cost_manager.check_and_record_usage(estimated_tokens)       │
└─────────────────────────────────────────────────────────────┘
                           ↓
                    ┌──────┴──────┐
                    │  Within     │
                    │  Budget?    │
                    └──────┬──────┘
                      No ↙    ↘ Yes
        ┌─────────────────┐   ┌──────────────────────┐
        │ Raise           │   │ Record estimated     │
        │ BudgetExhausted │   │ usage                │
        │ Error           │   └──────────┬───────────┘
        └─────────────────┘              ↓
                              ┌──────────────────────┐
                              │ CALL LLM API         │
                              └──────────┬───────────┘
                                         ↓
                              ┌──────────────────────┐
                              │ LLM RESPONSE         │
                              │ • actual_prompt_tkns │
                              │ • completion_tokens  │
                              └──────────┬───────────┘
                                         ↓
                              ┌──────────────────────┐
                              │ ADJUST USAGE         │
                              │ • Calculate diff:    │
                              │   actual - estimated │
                              │ • Record adjustment  │
                              │ • Update state file  │
                              └──────────┬───────────┘
                                         ↓
                              ┌──────────────────────┐
                              │ RETURN RESPONSE      │
                              └──────────────────────┘
```

### Budget State Tracking

```
State File: autonomous_agent_state.json

{
  "current_period_start": "2025-11-01T00:00:00",
  "tokens_used_this_period": 45230,
  "cost_this_period": 1.3569
}
```

### Period Reset Flow

```
┌─────────────────────────────────────────────────────────────┐
│ BUDGET CHECK INVOKED                                        │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ CHECK IF NEW PERIOD                                         │
│ current_time >= period_end?                                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
                    ┌──────┴──────┐
                    │  New        │
                    │  Period?    │
                    └──────┬──────┘
                      No ↙    ↘ Yes
        ┌─────────────────┐   ┌──────────────────────┐
        │ Continue with   │   │ RESET STATE:         │
        │ current state   │   │ • period_start = now │
        │                 │   │ • tokens_used = 0    │
        │                 │   │ • cost = 0.0         │
        └─────────────────┘   └──────────┬───────────┘
                                         ↓
                              ┌──────────────────────┐
                              │ SAVE NEW STATE       │
                              └──────────────────────┘
```

### Code Reference

**File**: `autonomous_agent/cost_manager.py:125-184`

---

## Persistence and Recovery

### What Gets Persisted

```
┌──────────────────────────────────────────────────────────────┐
│ PERSISTENT STATE FILES                                       │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│ 1. tasks.json                                                │
│    • All tasks with their statuses                           │
│    • Updated after every status change                       │
│    • Survives system reboots                                 │
│                                                              │
│ 2. autonomous_agent_state.json                               │
│    • Token usage for current period                          │
│    • Cost tracking                                           │
│    • Period start timestamp                                  │
│    • Survives system reboots                                 │
│                                                              │
│ 3. Git Commits                                               │
│    • Completed task changes in branches                      │
│    • Commit messages with task IDs                           │
│    • Permanent record of work done                           │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### Crash Recovery Flow

```
                    ┌─────────────────┐
                    │ SYSTEM CRASHES  │
                    │ or              │
                    │ ORCHESTRATOR    │
                    │ KILLED          │
                    └────────┬────────┘
                             ↓
                    ┌────────────────┐
                    │ System Reboots │
                    │ or             │
                    │ User Restarts  │
                    └────────┬───────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ RESTART: python run_orchestrator.py                        │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ LOAD PERSISTENT STATE                                       │
│ • tasks.json → TaskQueue                                    │
│ • autonomous_agent_state.json → TokenCostManager            │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ ANALYZE TASK STATES                                         │
├─────────────────────────────────────────────────────────────┤
│ • "completed" tasks: Keep as-is (never re-run)              │
│ • "failed" tasks: Keep as-is (manual intervention needed)   │
│ • "pending" tasks: Will be processed normally               │
│ • "in_progress" tasks: STUCK - require manual reset         │
└─────────────────────────────────────────────────────────────┘
                             ↓
┌─────────────────────────────────────────────────────────────┐
│ RESUME NORMAL OPERATION                                     │
│ • Start from first "pending" task                           │
│ • Budget tracking continues from saved state                │
│ • No duplicate work performed                               │
└─────────────────────────────────────────────────────────────┘
```

### Code Reference

**File**: `autonomous_agent/task_queue.py:41-52` (load)
**File**: `autonomous_agent/task_queue.py:54-57` (save)
**File**: `autonomous_agent/cost_manager.py:48-69` (state management)

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR LIFECYCLE                   │
└─────────────────────────────────────────────────────────────┘

  START
    │
    ↓
  [Load Config] ──→ config.autonomous.toml
    │
    ↓
  [Initialize Components]
    ├─→ OpenHandsConfig
    ├─→ LLMRegistry
    ├─→ TokenCostManager
    └─→ GitWorkspace
    │
    ↓
  [Wrap LLM] ──→ Budget-aware LLM client
    │
    ↓
  [Load/Parse Tasks]
    ├─→ Load tasks.json (if exists)
    └─→ Parse tasks/*.md (if queue empty)
    │
    ↓
┌─┴──────────────────────────────────────────────────────────┐
│ MAIN LOOP START                                            │
└─┬──────────────────────────────────────────────────────────┘
  │
  ├─→ [Get Next Task] ──→ Only "pending" tasks
  │         │
  │         ├─→ No tasks? ──→ EXIT
  │         │
  │         ↓ Yes
  │   [Update Status] ──→ "in_progress"
  │         │
  │         ↓
  │   [Create Git Branch] ──→ agent/task-{id}
  │         │
  │         ↓
  │   [Initialize Session]
  │         │
  │         ↓
  │   [Start Agent] ──→ AgentSession.start()
  │         │              │
  │         │              ↓
  │         │         [Agent Executes]
  │         │              ├─→ LLM Calls
  │         │              │   ├─→ Budget Check
  │         │              │   ├─→ Rate Limit Retry
  │         │              │   └─→ Token Tracking
  │         │              │
  │         │              ├─→ File Operations
  │         │              ├─→ Shell Commands
  │         │              └─→ Task Completion
  │         │
  │         ↓
  │   [Poll for Completion] ──→ Every 5s
  │         │
  │         ↓
  │   ┌───[Check State]───┐
  │   │                    │
  │   ↓                    ↓                    ↓
  │ "finished"      "error/stopped"      Exception
  │   │                    │                    │
  │   ↓                    ↓                    ↓
  │ [Commit]          [Log Error]        [Check Type]
  │ [Status:          [Status:                 │
  │  completed]        failed]                 │
  │   │                    │              ┌─────┼─────┐
  │   │                    │              ↓     ↓     ↓
  │   │                    │          Budget Rate  Other
  │   │                    │          Error  Limit Error
  │   │                    │            │      │      │
  │   │                    │            ↓      ↓      ↓
  │   │                    │        [Re-queue][Sleep][Fail]
  │   │                    │                            │
  │   ↓                    ↓                            ↓
  │ [Cleanup] ←──────────────────────────────────→ [Reset]
  │   │                                                │
  │   ↓                                                ↓
  │ [Checkout Original Branch]                   [Checkout]
  │   │                                                │
  │   └────────────────────┬───────────────────────────┘
  │                        ↓
  │                  [Save State]
  │                        │
  └────────────────────────┘
                           │
                           ↓
                      LOOP BACK
                           │
                           ↓
                    No more tasks
                           │
                           ↓
                         EXIT
```

---

## Summary Table

| Phase | Key Actions | Persistent State | Recovery |
|-------|-------------|------------------|----------|
| **Startup** | Load config, init components, parse tasks | tasks.json, state.json | Full state restored |
| **Task Selection** | Get next pending task | None | Completed/failed tasks skipped |
| **Execution** | Run agent, track budget, make changes | Token usage updated | In-progress tasks stuck on crash |
| **Success** | Commit to Git, mark completed | Task status saved | Work preserved in Git |
| **Failure** | Log error, reset branch, mark failed | Task status saved | Changes discarded |
| **Budget Hit** | Re-queue task, sleep until reset | Task re-queued | Will retry after sleep |
| **Cleanup** | Close session, restore branch | All state saved | Clean state for next task |

---

## Key Design Principles

1. **Idempotency**: Completed tasks never re-run
2. **Durability**: All state persisted to disk
3. **Safety**: Conservative error handling prevents duplicate work
4. **Transparency**: Full state visible in JSON files
5. **Recoverability**: Graceful recovery from crashes
6. **Budget-Aware**: Proactive and reactive budget management
7. **Isolation**: Each task in separate Git branch

---

## Related Documentation

- **[TASK_LIFECYCLE.md](TASK_LIFECYCLE.md)** - Detailed task state management
- **[README.md](README.md)** - Setup and usage guide
- **[AUTONOMOUS_AGENT_STATUS.md](AUTONOMOUS_AGENT_STATUS.md)** - Implementation status
- **[docs/AUTONOMOUS_CODING_AGENT.md](docs/AUTONOMOUS_CODING_AGENT.md)** - Architecture design

---

**Last Updated**: 2025-11-21
**Status**: Production Ready
**Test Coverage**: 45/45 tests passing ✅
