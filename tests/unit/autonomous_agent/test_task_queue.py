"""Tests for the TaskQueue class."""
import json
import os
import tempfile
import pytest

from autonomous_agent.task_queue import Task, TaskQueue, VALID_STATUSES


class TestTask:
    """Tests for the Task dataclass."""

    def test_task_creation(self):
        """Test creating a task with valid parameters."""
        task = Task(
            id="test-123",
            file_path="/path/to/task.md",
            description="Test task description",
        )
        assert task.id == "test-123"
        assert task.file_path == "/path/to/task.md"
        assert task.description == "Test task description"
        assert task.status == "pending"
        assert task.history == []

    def test_task_to_dict(self):
        """Test converting a task to a dictionary."""
        task = Task(
            id="test-123",
            file_path="/path/to/task.md",
            description="Test task description",
            status="completed",
        )
        task_dict = task.to_dict()
        assert task_dict["id"] == "test-123"
        assert task_dict["file_path"] == "/path/to/task.md"
        assert task_dict["description"] == "Test task description"
        assert task_dict["status"] == "completed"
        assert task_dict["history"] == []


class TestTaskQueue:
    """Tests for the TaskQueue class."""

    @pytest.fixture
    def temp_queue_file(self):
        """Create a temporary file for the task queue."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
        yield temp_file
        # Cleanup
        if os.path.exists(temp_file):
            os.remove(temp_file)

    def test_init_with_new_file(self, temp_queue_file):
        """Test initializing a TaskQueue with a new file."""
        queue = TaskQueue(queue_file=temp_queue_file)
        assert len(queue.get_all_tasks()) == 0

    def test_add_task(self, temp_queue_file):
        """Test adding a task to the queue."""
        queue = TaskQueue(queue_file=temp_queue_file)
        task = Task(
            id="task-1",
            file_path="/path/to/task1.md",
            description="First task",
        )
        queue.add_task(task)

        tasks = queue.get_all_tasks()
        assert len(tasks) == 1
        assert tasks[0].id == "task-1"
        assert tasks[0].description == "First task"

    def test_add_duplicate_task(self, temp_queue_file):
        """Test that duplicate tasks are not added."""
        queue = TaskQueue(queue_file=temp_queue_file)
        task1 = Task(id="task-1", file_path="/path/to/task.md", description="Task")
        task2 = Task(id="task-1", file_path="/path/to/task.md", description="Task")

        queue.add_task(task1)
        queue.add_task(task2)

        assert len(queue.get_all_tasks()) == 1

    def test_get_next_task(self, temp_queue_file):
        """Test getting the next pending task."""
        queue = TaskQueue(queue_file=temp_queue_file)
        task1 = Task(id="task-1", file_path="/p1.md", description="Task 1")
        task2 = Task(id="task-2", file_path="/p2.md", description="Task 2")

        queue.add_task(task1)
        queue.add_task(task2)

        next_task = queue.get_next_task()
        assert next_task.id == "task-1"

    def test_get_next_task_skips_non_pending(self, temp_queue_file):
        """Test that get_next_task skips non-pending tasks."""
        queue = TaskQueue(queue_file=temp_queue_file)
        task1 = Task(id="task-1", file_path="/p1.md", description="Task 1", status="completed")
        task2 = Task(id="task-2", file_path="/p2.md", description="Task 2", status="pending")

        queue.add_task(task1)
        queue.add_task(task2)

        next_task = queue.get_next_task()
        assert next_task.id == "task-2"

    def test_get_next_task_empty_queue(self, temp_queue_file):
        """Test getting next task from empty queue."""
        queue = TaskQueue(queue_file=temp_queue_file)
        assert queue.get_next_task() is None

    def test_update_task_status(self, temp_queue_file):
        """Test updating a task's status."""
        queue = TaskQueue(queue_file=temp_queue_file)
        task = Task(id="task-1", file_path="/p.md", description="Task")
        queue.add_task(task)

        queue.update_task_status("task-1", "in_progress")
        tasks = queue.get_all_tasks()
        assert tasks[0].status == "in_progress"

    def test_update_task_status_invalid_status(self, temp_queue_file):
        """Test that invalid status raises ValueError."""
        queue = TaskQueue(queue_file=temp_queue_file)
        task = Task(id="task-1", file_path="/p.md", description="Task")
        queue.add_task(task)

        with pytest.raises(ValueError, match="Invalid status"):
            queue.update_task_status("task-1", "invalid_status")

    def test_update_task_status_nonexistent_task(self, temp_queue_file):
        """Test that updating a nonexistent task raises ValueError."""
        queue = TaskQueue(queue_file=temp_queue_file)

        with pytest.raises(ValueError, match="not found"):
            queue.update_task_status("nonexistent", "completed")

    def test_persistence(self, temp_queue_file):
        """Test that tasks are persisted to file."""
        queue1 = TaskQueue(queue_file=temp_queue_file)
        task = Task(id="task-1", file_path="/p.md", description="Persistent task")
        queue1.add_task(task)

        # Create a new queue instance with the same file
        queue2 = TaskQueue(queue_file=temp_queue_file)
        tasks = queue2.get_all_tasks()

        assert len(tasks) == 1
        assert tasks[0].id == "task-1"
        assert tasks[0].description == "Persistent task"

    def test_load_corrupted_file(self, temp_queue_file):
        """Test that corrupted JSON file is handled gracefully."""
        with open(temp_queue_file, 'w') as f:
            f.write("corrupted json {{{")

        queue = TaskQueue(queue_file=temp_queue_file)
        assert len(queue.get_all_tasks()) == 0
