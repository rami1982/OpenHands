import asyncio
import os
import time
import toml
from datetime import datetime

from openhands.controller.agent import Agent
from openhands.core.config import OpenHandsConfig, LLMConfig
from openhands.core.logger import openhands_logger as logger
from openhands.events.action import MessageAction
from openhands.llm.llm_registry import LLMRegistry
from openhands.server.session.agent_session import AgentSession
from openhands.storage.local import LocalFileStore
from openhands.server.services.conversation_stats import ConversationStats

from autonomous_agent.cost_manager import (
    TokenCostManager,
    BudgetExhaustedError,
    ExtendedRateLimitError,
)
from autonomous_agent.task_queue import TaskQueue
from autonomous_agent.workspace import GitWorkspace
from autonomous_agent.parsers.md_parser import parse_markdown_files

async def main():
    """Main entry point for the orchestrator daemon."""

    # 1. Load Orchestrator Configuration
    try:
        with open("config.autonomous.toml", "r") as f:
            orchestrator_config = toml.load(f)
    except FileNotFoundError:
        logger.error("Error: config.autonomous.toml not found.")
        return

    # 2. Initialize Core OpenHands Components
    config = OpenHandsConfig()
    llm_registry = LLMRegistry(config)
    cost_manager = TokenCostManager(config=orchestrator_config.get("cost_management", {}))

    # Get the default LLM and wrap it with the cost manager
    # We are assuming a single agent/llm setup for now
    default_llm = llm_registry.get_llm()
    budget_aware_llm = cost_manager.get_wrapped_llm_client(default_llm)
    
    # We need to update the registry with the wrapped LLM, or pass it to the agent
    # The AgentSession takes an agent, so we create it here
    agent_config = config.get_agent_config()
    agent = Agent(llm=budget_aware_llm, config=agent_config)

    # 3. Initialize Task Queue
    task_queue = TaskQueue(queue_file="tasks.json")
    if not task_queue.get_all_tasks():
        task_source_config = orchestrator_config.get("task_source", {})
        if task_source_config.get("type") == "markdown":
            md_path = task_source_config.get("path", "tasks/")
            tasks = parse_markdown_files(md_path)
            for task in tasks:
                task_queue.add_task(task)
            logger.info(f"Loaded {len(tasks)} tasks from {md_path}")

    # 4. Main Orchestration Loop
    while True:
        task = task_queue.get_next_task()
        if not task:
            logger.info("No more pending tasks. Orchestrator finished.")
            break

        logger.info(f"Starting task: {task.id} - {task.description[:100]}...")
        task_queue.update_task_status(task.id, "in_progress")
        
        workspace = None
        session = None
        try:
            # a. Setup Workspace
            workspace = GitWorkspace()
            branch_name = f"{orchestrator_config.get('git', {}).get('branch_prefix', 'agent/task-')}{task.id[:12]}"
            if not workspace.create_branch(branch_name):
                raise RuntimeError(f"Could not create git branch {branch_name}")

            # b. Initialize session components
            session_id = f"session-{task.id[:12]}"
            file_store = LocalFileStore(session_id)
            conversation_stats = ConversationStats(session_id)
            
            # c. Create and start AgentSession
            session = AgentSession(
                sid=session_id,
                file_store=file_store,
                llm_registry=llm_registry,
                conversation_stats=conversation_stats,
            )
            
            initial_message = MessageAction(source="user", content=task.description)

            # The session will use the agent we created with the wrapped LLM
            await session.start(
                runtime_name=config.runtime,
                config=config,
                agent=agent,
                max_iterations=config.max_iterations,
                initial_message=initial_message,
            )

            # d. Wait for session to complete
            while session.controller and session.controller.get_agent_state() not in ["finished", "error", "stopped", "rejected", "paused"]:
                await asyncio.sleep(5) # Poll every 5 seconds

            # e. Handle Task Outcome
            final_state = session.controller.get_agent_state()
            if final_state == "finished":
                logger.info(f"Task {task.id} completed successfully.")
                workspace.add_all_and_commit(f"feat: complete task {task.id}\n\n{task.description}")
                task_queue.update_task_status(task.id, "completed")
            else:
                raise RuntimeError(f"Agent stopped with state: {final_state}")

        except (BudgetExhaustedError, ExtendedRateLimitError) as e:
            logger.warning(f"Pausing orchestrator due to: {e}")
            task_queue.update_task_status(task.id, "pending") # Re-queue the task
            
            if isinstance(e, BudgetExhaustedError) and e.reset_time:
                sleep_duration = (e.reset_time - datetime.utcnow()).total_seconds()
                if sleep_duration > 0:
                    logger.info(f"Sleeping for {sleep_duration:.0f} seconds until budget resets.")
                    time.sleep(sleep_duration)
            else:
                cooldown = orchestrator_config.get("rate_limits", {}).get("cooldown_period_on_extended_rate_limit", 3600)
                logger.info(f"Cooling down for {cooldown} seconds.")
                time.sleep(cooldown)
            continue # Re-try the task after pausing

        except Exception as e:
            logger.error(f"An error occurred while processing task {task.id}: {e}", exc_info=True)
            task_queue.update_task_status(task.id, "failed")
            if workspace:
                workspace.reset_branch() # Revert changes on failure
        
        finally:
            # f. Cleanup
            if session:
                await session.close()
            if workspace:
                workspace.checkout_original_branch()


if __name__ == "__main__":
    # Setup basic logging
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Orchestrator stopped by user.")