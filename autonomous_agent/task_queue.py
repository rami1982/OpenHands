import json
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict

# Defines the valid states a task can be in
VALID_STATUSES = ["pending", "in_progress", "completed", "failed"]

@dataclass
class Task:
    """Represents a single task in the queue."""
    id: str
    file_path: str
    description: str
    status: str = "pending"
    history: List[Dict] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "file_path": self.file_path,
            "description": self.description,
            "status": self.status,
            "history": self.history,
        }

class TaskQueue:
    """Manages a file-based queue of tasks."""

    def __init__(self, queue_file: str = "tasks.json"):
        """
        Initializes the TaskQueue.

        Args:
            queue_file: The path to the JSON file used as the queue.
        """
        self.queue_file = queue_file
        self.tasks: List[Task] = []
        self._load_tasks()

    def _load_tasks(self):
        """Loads tasks from the JSON queue file."""
        if os.path.exists(self.queue_file):
            with open(self.queue_file, "r") as f:
                try:
                    task_data = json.load(f)
                    self.tasks = [Task(**data) for data in task_data]
                except (json.JSONDecodeError, TypeError):
                    # If file is empty, corrupted, or not a list of dicts, start fresh
                    self.tasks = []
        else:
            self.tasks = []

    def _save_tasks(self):
        """Saves the current list of tasks to the JSON queue file."""
        with open(self.queue_file, "w") as f:
            json.dump([task.to_dict() for task in self.tasks], f, indent=4)

    def add_task(self, task: Task):
        """
        Adds a new task to the queue if it doesn't already exist.

        Args:
            task: The Task object to add.
        """
        if not any(t.id == task.id for t in self.tasks):
            self.tasks.append(task)
            self._save_tasks()

    def get_next_task(self) -> Optional[Task]:
        """
        Retrieves the next pending task from the queue.

        Returns:
            The next task with "pending" status, or None if no pending tasks are available.
        """
        for task in self.tasks:
            if task.status == "pending":
                return task
        return None

    def update_task_status(self, task_id: str, status: str):
        """
        Updates the status of a specific task.

        Args:
            task_id: The ID of the task to update.
            status: The new status to set.

        Raises:
            ValueError: If the status is invalid or the task ID is not found.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Must be one of {VALID_STATUSES}")

        task_found = False
        for task in self.tasks:
            if task.id == task_id:
                task.status = status
                task_found = True
                break
        
        if not task_found:
            raise ValueError(f"Task with ID '{task_id}' not found in the queue.")

        self._save_tasks()

    def get_all_tasks(self) -> List[Task]:
        """Returns a copy of all tasks in the queue."""
        return self.tasks.copy()
