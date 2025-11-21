# Original OpenHands README (with its original fucntionality
[Original OpenHands README with its original fucntionality](PREV_OH_README.md)

# Autonomous Agent Orchestrator for OpenHands

This project introduces an autonomous orchestrator layer designed to run on top of the OpenHands AI coding agent. It enables OpenHands to work through a large backlog of development tasks automatically, without requiring user input for each task.

The system is designed to be mindful of budgets, with a cost management component that tracks API token usage against a defined monthly or daily limit. If the limit is reached, the agent will automatically pause and resume its work once the API quota has been reset.

## How It Works

The orchestrator runs as a background service (`daemon`) that manages the entire lifecycle of task execution.

1.  **Task Queue**: The system reads development tasks from a configurable source, such as a directory of Markdown files, and loads them into a queue.
2.  **Orchestration Loop**: The orchestrator picks up the next pending task from the queue.
3.  **Isolated Workspace**: For each task, it automatically creates a new Git branch to keep the work isolated.
4.  **Agent Execution**: It invokes the core OpenHands agent to perform the task.
5.  **Cost & Limit Management**: All LLM API calls are routed through a **Token/Cost Manager**. This component monitors token consumption. If the predefined budget is exceeded, it pauses the orchestrator until the limit period (e.g., the next day or month) begins.
6.  **Task Completion**:
    -   If a task is completed successfully, the changes are committed to the feature branch.
    -   If a task fails, the orchestrator logs the error, discards the changes, and proceeds to the next task.

This architecture allows a development team to load a large number of tasks into the system and have the AI agent work on them continuously and autonomously, maximizing productivity while controlling costs.

## Getting Started

The autonomous orchestrator has been implemented and is ready to use. Here's how to get started:

### Prerequisites

1. **Install Dependencies**: Ensure you have the required dependencies installed:
   ```bash
   pip install gitpython tenacity
   ```

   Or add them to your Poetry environment:
   ```bash
   poetry add gitpython tenacity
   ```

### Setup and Usage

1.  **Configure the Orchestrator**:
    -   A `config.autonomous.toml` file has been provided with sensible defaults.
    -   You can modify the task source path, API budget, cost per 1000 tokens, and Git settings.
    -   Key configuration options:
        -   `token_budget`: Set to `0` for unlimited usage, or specify a monthly/daily/hourly token limit
        -   `budget_period`: Can be `"monthly"`, `"daily"`, or `"hourly"`
        -   `cost_per_1000_tokens`: Adjust based on your LLM provider's pricing

2.  **Define Tasks**:
    -   Add markdown files to the `tasks/` directory. Each file represents a single task for the agent to work on.
    -   Example task file (`tasks/fix_bug.md`):
      ```markdown
      # Fix Authentication Bug

      There's a bug in the user authentication flow where...
      (task description)
      ```

3.  **Run the Orchestrator**:
    -   Start the autonomous agent daemon from the command line:
    ```bash
    python run_orchestrator.py
    ```

The agent will then:
- Load all pending tasks from the queue
- Pick up each task one by one
- Create an isolated Git branch for each task
- Invoke the OpenHands agent to complete the task
- Commit successful changes and handle failures gracefully
- Pause automatically if API budget limits are reached
- Resume when the budget period resets

## Implementation Status

The following components have been fully implemented:

- ✅ **Task Queue** (`autonomous_agent/task_queue.py`): File-based task queue with status tracking
- ✅ **Cost Manager** (`autonomous_agent/cost_manager.py`): Budget tracking and rate limit handling
- ✅ **Git Workspace** (`autonomous_agent/workspace.py`): Branch management and commit automation
- ✅ **Markdown Parser** (`autonomous_agent/parsers/md_parser.py`): Load tasks from .md files
- ✅ **Orchestrator Daemon** (`run_orchestrator.py`): Main orchestration loop
- ✅ **Configuration** (`config.autonomous.toml`): Comprehensive configuration options
- ✅ **Unit Tests** (`tests/unit/autonomous_agent/`): Test coverage for core components

## Architecture

The system consists of:

1. **autonomous_agent/** - Core orchestration components
   - `task_queue.py` - Task management with file-based persistence
   - `cost_manager.py` - API budget tracking and rate limit retry logic
   - `workspace.py` - Git operations wrapper using GitPython
   - `parsers/md_parser.py` - Markdown task file parser

2. **run_orchestrator.py** - Main entry point that:
   - Loads configuration from `config.autonomous.toml`
   - Wraps the OpenHands LLM client with cost management
   - Runs the main orchestration loop
   - Handles graceful pausing/resuming on budget/rate limits

3. **config.autonomous.toml** - Configuration file for:
   - Task sources
   - API budgets and costs
   - Git branch naming
   - Rate limit retry behavior

## Notes and Limitations

- The orchestrator requires OpenHands to be properly installed and configured
- API keys and LLM configuration should be set up in OpenHands config files
- The system creates Git branches automatically - ensure you're working in a Git repository
- For production use, consider setting appropriate token budgets to avoid unexpected API costs


