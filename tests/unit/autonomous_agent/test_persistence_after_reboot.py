"""Test that completed tasks are not re-run after system reboot."""
import tempfile
import os
import pytest

from autonomous_agent.task_queue import Task, TaskQueue


class TestPersistenceAfterReboot:
    """Test task persistence across orchestrator restarts."""

    @pytest.fixture
    def temp_queue_file(self):
        """Create a temporary file for the task queue."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_file = f.name
        yield temp_file
        if os.path.exists(temp_file):
            os.remove(temp_file)

    def test_completed_tasks_not_rerun_after_reboot(self, temp_queue_file):
        """
        Simulate a system reboot scenario:
        1. Create tasks and mark one as completed
        2. "Reboot" by creating a new TaskQueue instance
        3. Verify completed task is NOT returned by get_next_task()
        """
        # Initial run - create tasks
        queue1 = TaskQueue(queue_file=temp_queue_file)
        task1 = Task(id="task-1", file_path="/t1.md", description="First task")
        task2 = Task(id="task-2", file_path="/t2.md", description="Second task")
        task3 = Task(id="task-3", file_path="/t3.md", description="Third task")

        queue1.add_task(task1)
        queue1.add_task(task2)
        queue1.add_task(task3)

        # Complete first task
        queue1.update_task_status("task-1", "completed")

        # Simulate system reboot - create new queue instance
        # This loads from the persisted file
        queue2 = TaskQueue(queue_file=temp_queue_file)

        # After reboot, next task should be task-2, NOT task-1
        next_task = queue2.get_next_task()
        assert next_task is not None
        assert next_task.id == "task-2", "Should skip completed task-1"

        # Mark task-2 as completed
        queue2.update_task_status("task-2", "completed")

        # Another reboot
        queue3 = TaskQueue(queue_file=temp_queue_file)

        # Should now get task-3
        next_task = queue3.get_next_task()
        assert next_task is not None
        assert next_task.id == "task-3", "Should skip both completed tasks"

        # Complete all tasks
        queue3.update_task_status("task-3", "completed")

        # Final reboot - all tasks completed
        queue4 = TaskQueue(queue_file=temp_queue_file)

        # Should return None (no pending tasks)
        next_task = queue4.get_next_task()
        assert next_task is None, "All tasks completed, should return None"

    def test_failed_tasks_can_be_retried(self, temp_queue_file):
        """
        Test that failed tasks remain available for retry.
        """
        queue1 = TaskQueue(queue_file=temp_queue_file)
        task = Task(id="task-1", file_path="/t1.md", description="Task")
        queue1.add_task(task)

        # Mark as failed
        queue1.update_task_status("task-1", "failed")

        # Reboot
        queue2 = TaskQueue(queue_file=temp_queue_file)

        # Failed tasks are NOT automatically retried
        # They need to be manually reset to "pending" if retry is desired
        next_task = queue2.get_next_task()
        assert next_task is None, "Failed tasks should not be auto-retried"

        # Manually reset to pending for retry
        queue2.update_task_status("task-1", "pending")

        # Now it should be available
        next_task = queue2.get_next_task()
        assert next_task is not None
        assert next_task.id == "task-1"

    def test_in_progress_tasks_after_crash(self, temp_queue_file):
        """
        Test behavior when orchestrator crashes with a task in_progress.
        """
        queue1 = TaskQueue(queue_file=temp_queue_file)
        task = Task(id="task-1", file_path="/t1.md", description="Task")
        queue1.add_task(task)

        # Mark as in_progress (simulating crash during execution)
        queue1.update_task_status("task-1", "in_progress")

        # Reboot after crash
        queue2 = TaskQueue(queue_file=temp_queue_file)

        # In-progress tasks are NOT automatically retried
        # This is safe behavior to avoid duplicate work
        next_task = queue2.get_next_task()
        assert next_task is None, "In-progress tasks should not be auto-retried"

        # Admin can manually reset to pending if needed
        queue2.update_task_status("task-1", "pending")
        next_task = queue2.get_next_task()
        assert next_task is not None

    def test_multiple_reboots_with_mixed_statuses(self, temp_queue_file):
        """
        Test realistic scenario with multiple reboots and mixed task statuses.
        """
        # Initial setup
        queue = TaskQueue(queue_file=temp_queue_file)
        for i in range(5):
            task = Task(id=f"task-{i}", file_path=f"/t{i}.md", description=f"Task {i}")
            queue.add_task(task)

        # Run 1: Complete task-0
        next_task = queue.get_next_task()
        assert next_task.id == "task-0"
        queue.update_task_status("task-0", "completed")

        # Reboot 1
        queue = TaskQueue(queue_file=temp_queue_file)
        next_task = queue.get_next_task()
        assert next_task.id == "task-1"
        queue.update_task_status("task-1", "completed")

        # Reboot 2
        queue = TaskQueue(queue_file=temp_queue_file)
        next_task = queue.get_next_task()
        assert next_task.id == "task-2"
        queue.update_task_status("task-2", "failed")  # This one fails

        # Reboot 3 - should skip to task-3
        queue = TaskQueue(queue_file=temp_queue_file)
        next_task = queue.get_next_task()
        assert next_task.id == "task-3"
        queue.update_task_status("task-3", "completed")

        # Reboot 4
        queue = TaskQueue(queue_file=temp_queue_file)
        next_task = queue.get_next_task()
        assert next_task.id == "task-4"
        queue.update_task_status("task-4", "completed")

        # Reboot 5 - all done except the failed one
        queue = TaskQueue(queue_file=temp_queue_file)
        next_task = queue.get_next_task()
        assert next_task is None

        # Verify final state
        all_tasks = queue.get_all_tasks()
        assert len([t for t in all_tasks if t.status == "completed"]) == 4
        assert len([t for t in all_tasks if t.status == "failed"]) == 1
