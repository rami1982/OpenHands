import os
import hashlib
from typing import List

from autonomous_agent.task_queue import Task

def parse_markdown_files(directory: str) -> List[Task]:
    """
    Parses all markdown files in a given directory and creates a list of tasks.

    Each .md file is treated as a separate task. The file's content is the
    description of the task. The task ID is a hash of the file path.

    Args:
        directory: The path to the directory containing the markdown files.

    Returns:
        A list of Task objects.
    """
    tasks = []
    if not os.path.isdir(directory):
        print(f"Warning: Directory not found at {directory}. No tasks will be loaded.")
        return tasks

    for filename in os.listdir(directory):
        if filename.endswith(".md"):
            file_path = os.path.join(directory, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                description = f.read()

            # Create a stable ID for the task based on its file path
            task_id = hashlib.sha256(file_path.encode()).hexdigest()

            task = Task(
                id=task_id,
                file_path=file_path,
                description=description,
            )
            tasks.append(task)
    
    return tasks
