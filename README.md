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

## Getting Started (Hypothetical Usage)

This feature is currently in the design phase. Once implemented, the workflow would be as follows:

1.  **Configure the Orchestrator**:
    -   Create a `config.autonomous.toml` file.
    -   Define the task source (e.g., `tasks/`), the API budget (`monthly_token_limit = 20000000`), and Git settings.

2.  **Define Tasks**:
    -   Add markdown files to the `tasks/` directory. Each file represents a single task for the agent to work on.

3.  **Run the Orchestrator**:
    -   Start the autonomous agent daemon from the command line:
    ```bash
    python run_orchestrator.py
    ```

The agent will then begin picking up tasks and working on them in separate branches, pausing and resuming as needed to respect API limits.