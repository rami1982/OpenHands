# Architecture Design: Autonomous Coding Agent Orchestrator

This document outlines the architecture for an orchestrator layer built on top of the existing OpenHands framework. The goal is to enable an AI agent to autonomously work through a predefined backlog of coding tasks, while managing API costs and respecting usage limits.

## 1. Overview

The proposed solution is an **Orchestrator Daemon** that runs as a persistent process. This daemon manages a queue of tasks, invokes the OpenHands agent for each task in a dedicated Git branch, and monitors API token consumption to stay within a budget. It is designed to be modular and requires minimal changes to the core OpenHands codebase, respecting the user's request to build on top of the existing platform.

The system will be composed of several new, distinct components that live outside the `openhands/` directory.

## 2. High-Level Architecture

```
+---------------------+      +---------------------+      +--------------------+
|   Task Parsers      |----->|     Task Queue      |<-----| Orchestrator Daemon|
| (MD, API, etc.)     |      | (tasks.json)        |      | (run_orchestrator.py)|
+---------------------+      +---------------------+      +----------+---------+
                                                                     |
                                                                     | (1. Get Next Task)
                                                                     v
+---------------------+      +---------------------+      +----------+---------+
| Git Workspace Mgr.  |<-----|  OpenHands Agent    |<-----|  Token/Cost Manager|
| (workspace.py)      |      | (Existing Core)     |      |  (cost_manager.py) |
+---------------------+      +---------------------+      +----------+---------+
          ^                          | (3. Execute Task)               ^
          |                          |                                 | (4. LLM Call via Wrapper)
          | (2. Create Branch)       v                                 |
          +--------------------------+---------------------------------+
```

**Flow:**
1.  **Task Loading:** Independent scripts (`parsers`) read tasks from various sources (e.g., a directory of `.md` files) and populate a central **Task Queue**.
2.  **Orchestration Loop:** The **Orchestrator Daemon** starts.
    a. It pulls the next available task from the queue.
    b. It uses the **Git Workspace Manager** to create a new, unique branch for the task (e.g., `agent/task-123-fix-bug`).
    c. It wraps the core OpenHands LLM client with the **Token/Cost Manager**.
    d. It invokes the main OpenHands agent process, passing the task description and the wrapped LLM client.
3.  **Task Execution:** The OpenHands agent executes the task as it normally would.
4.  **Cost and Rate Limit Management:** Every call to the LLM is intercepted by the **Token/Cost Manager**.
    a. **Proactive Budget Check:** It checks if the requested tokens exceed the predefined budget (e.g., monthly/daily token limit). If the budget is exhausted, it raises a `BudgetExhaustedError`.
    b. **Reactive Rate Limit Handling (within wrapper):** The LLM client calls are wrapped with a retry mechanism (e.g., using exponential backoff). If a `RateLimitError` (HTTP 429) is received, the wrapper will automatically retry the request for a configurable number of times, respecting `Retry-After` headers if available. If repeated retries fail, it raises an `ExtendedRateLimitError` to signal a persistent limit.
    c. If within budget and no immediate rate limit is encountered, it allows the LLM call to proceed and records the token usage.
5.  **Lifecycle Management:**
    a. **On Task Success:** The Orchestrator uses the Git Workspace Manager to commit the changes with a descriptive message.
    b. **On Rate Limit / Budget Exhaustion:**
        *   **`BudgetExhaustedError` (Proactive):** If the Orchestrator catches a `BudgetExhaustedError` (from the proactive budget check), it pauses all operations and calculates the time until the configured budget period resets. It will sleep until that time and then resume.
        *   **`ExtendedRateLimitError` (Reactive):** If the Orchestrator catches an `ExtendedRateLimitError` (signaling persistent rate limits after internal retries have failed), it pauses all operations for a configurable "cooldown" period (e.g., 1 hour, 4 hours) before resuming. This handles the unpredictable, longer-term rate limits.
    c. **On Task Failure:** The Orchestrator logs the error, resets the branch to its original state, and moves to the next task in the queue.

## 3. New Components

To implement this, the following new files/modules will be created outside the `openhands/` directory.

### 3.1. `autonomous_agent/`
A new top-level directory to house the orchestration logic.

#### `autonomous_agent/task_queue.py`
-   **Class:** `TaskQueue`
-   **Description:** A simple, file-based queue (e.g., using a JSON file) to manage the list of tasks. It will support adding tasks, retrieving the next pending task, and marking tasks as complete or failed. This can be upgraded to a more robust system like Redis in the future.
-   **Interface:** `add_task(task_details)`, `get_next_task()`, `update_task_status(task_id, status)`.

#### `autonomous_agent/cost_manager.py`
-   **Class:** `TokenCostManager`
-   **Description:** Manages API budget and handles transient LLM rate limits. It's initialized with a configuration specifying the subscription model, budget limits, cost per token, and parameters for rate limit retries and cooldowns. It provides a robust wrapper for the LLM client.
-   **Interface:**
    -   `get_wrapped_llm_client(original_llm)`: Returns an LLM client wrapped with both proactive budget checks and reactive rate limit retry logic.
    -   `check_and_record_usage(tokens)`: Checks against the proactive budget and records usage. Raises `BudgetExhaustedError` if the budget is met.
-   **Internal Logic:**
    -   **Proactive Budget Tracking:** Persists current usage to a state file to survive restarts.
    -   **Reactive Rate Limit Handling (within wrapper):**
        -   Wraps actual LLM API calls with a retry mechanism (e.g., using `tenacity` library).
        -   Catches specific `RateLimitError` exceptions (HTTP 429) from the underlying LLM client.
        -   Implements exponential backoff with jitter for retries.
        -   Respects `Retry-After` headers if provided by the API for precise waiting.
        -   If short-term retries are exhausted, it raises an `ExtendedRateLimitError` to the orchestrator, signaling a longer-term pause is required.
-   **Custom Exceptions:** Introduces `BudgetExhaustedError` and `ExtendedRateLimitError` for distinct handling by the Orchestrator.

#### `autonomous_agent/workspace.py`
-   **Class:** `GitWorkspace`
-   **Description:** An abstraction layer over Git commands using a library like `GitPython`. It will handle creating/checking out branches, committing work, and resetting the workspace.
-   **Interface:** `create_branch(branch_name)`, `commit(message)`, `reset_branch()`.

#### `autonomous_agent/parsers/`
-   **Description:** A directory containing different modules for parsing tasks from various sources.
-   `md_parser.py`: Parses a directory of markdown files, where each file represents a task. The file's content is the task description.
-   `api_parser.py`: (Future extension) Parses tasks from an API endpoint like Jira or GitHub Issues.

### 3.2. `run_orchestrator.py`
-   **Description:** The main entry point for the autonomous agent system. This script initializes all the manager components and starts the main orchestration loop.

### 3.3. `config.autonomous.toml`
-   **Description:** A new configuration file, separate from OpenHands's main config. It will define settings for the orchestrator, including:
    -   Task source (e.g., path to MD files).
    -   Cost management parameters (budget, period, API costs).
    -   Git settings (e.g., branch prefixes).

## 4. Integration with OpenHands (Minimal Changes)

The key to minimizing changes is dependency injection.

1.  **LLM Client Wrapping:** The `run_orchestrator.py` script will be responsible for initializing the core `openhands.llm.LLM` class. Before passing it to the OpenHands `Controller` or `Agent`, it will wrap it using the `TokenCostManager`.
    ```python
    # In run_orchestrator.py
    from openhands.llm import LLM
    from autonomous_agent.cost_manager import TokenCostManager

    # 1. Init cost manager from config
    cost_manager = TokenCostManager(config.cost_management)

    # 2. Init the original LLM
    original_llm = LLM(config.llm)

    # 3. Get a wrapped, budget-aware client
    budget_aware_llm = cost_manager.get_wrapped_llm_client(original_llm)

    # 4. Pass the wrapped client to the agent
    agent = Agent(llm=budget_aware_llm)
    agent.run(task)
    ```
2.  **No Core Logic Change:** By using a wrapper, the `TokenCostManager` is transparent to the OpenHands agent. The agent makes LLM calls as usual, but the wrapper intercepts them to check the budget. This requires **zero changes** to the agent's internal logic, provided the wrapper perfectly mimics the `LLM` class interface.

## 5. Existing OpenHands Functionality

The current OpenHands system provides the core "worker agent" functionality. It excels at taking a single, well-defined task and attempting to solve it. The proposed architecture does not replace this; it wraps it in a long-running, autonomous loop. We will leverage:
-   **`Agent` classes:** The core implementation logic for solving tasks.
-   **`Controller`:** The high-level entry point for running a single task.
-   **Skills/Tools:** The entire ecosystem of tools (e.g., file operations, shell commands) available to the agent.

This design fulfills the request by creating a new, autonomous capability layer around OpenHands while ensuring that the core components remain decoupled and largely unmodified.
