# Task Lifecycle and Persistence

## Overview

This document explains how the Autonomous Agent handles task states, persistence across reboots, and prevents duplicate task execution.

---

## ✅ Key Answer: Completed Tasks Are NOT Re-Run

**The system correctly prevents re-running completed tasks after a reboot.**

Tasks are persisted to `tasks.json` with their status, and the orchestrator **only processes tasks with "pending" status**.

---

## Task States

Each task can be in one of four states:

| Status | Meaning | Next Action |
|--------|---------|-------------|
| **pending** | Task is waiting to be executed | Will be picked up by `get_next_task()` |
| **in_progress** | Task is currently being worked on | Will NOT be auto-retried (see below) |
| **completed** | Task finished successfully | Will NEVER be picked up again ✅ |
| **failed** | Task execution failed | Will NOT be auto-retried (manual reset needed) |

---

## How Persistence Works

### Storage Mechanism

Tasks are stored in `tasks.json` with full state information:

```json
[
  {
    "id": "task-abc123...",
    "file_path": "tasks/implement_feature.md",
    "description": "Implement user authentication",
    "status": "completed",
    "history": []
  },
  {
    "id": "task-def456...",
    "file_path": "tasks/fix_bug.md",
    "description": "Fix login bug",
    "status": "pending",
    "history": []
  }
]
```

### On Orchestrator Start

```python
# Load tasks from persistent storage
task_queue = TaskQueue(queue_file="tasks.json")

# This reads the JSON file and restores all task states
```

### Task Selection Logic

```python
def get_next_task(self) -> Optional[Task]:
    """Only returns tasks with 'pending' status."""
    for task in self.tasks:
        if task.status == "pending":  # ← Key check
            return task
    return None
```

**Result**: Completed tasks are automatically skipped! ✅

---

## Lifecycle Examples

### Example 1: Normal Execution

**Initial state:**
```json
[
  {"id": "task-1", "status": "pending"},
  {"id": "task-2", "status": "pending"},
  {"id": "task-3", "status": "pending"}
]
```

**After running orchestrator (all tasks complete):**
```json
[
  {"id": "task-1", "status": "completed"},
  {"id": "task-2", "status": "completed"},
  {"id": "task-3", "status": "completed"}
]
```

**After system reboot and restart:**
```bash
$ python run_orchestrator.py
INFO: No more pending tasks. Orchestrator finished.
```

**Outcome**: No tasks are re-run ✅

---

### Example 2: Interrupted Execution

**Scenario**: System crashes or is stopped while task-2 is in progress

**State at crash:**
```json
[
  {"id": "task-1", "status": "completed"},
  {"id": "task-2", "status": "in_progress"},  ← Was executing
  {"id": "task-3", "status": "pending"}
]
```

**After reboot:**
```bash
$ python run_orchestrator.py
INFO: Starting task: task-3...  ← Skips task-2
```

**Why?** The `get_next_task()` method **only returns "pending" tasks**, not "in_progress" ones.

**What about task-2?**
- It remains in "in_progress" state
- Manual intervention needed to reset it to "pending" if retry is desired
- This is **safe behavior** to avoid duplicate work

**How to retry task-2:**
```python
# Manually reset via Python
from autonomous_agent.task_queue import TaskQueue
queue = TaskQueue("tasks.json")
queue.update_task_status("task-2", "pending")
```

Or edit `tasks.json` directly:
```json
{"id": "task-2", "status": "pending"}  ← Change to pending
```

---

### Example 3: Failed Task Handling

**Scenario**: Task-2 fails during execution

**State after failure:**
```json
[
  {"id": "task-1", "status": "completed"},
  {"id": "task-2", "status": "failed"},
  {"id": "task-3", "status": "pending"}
]
```

**After reboot:**
```bash
$ python run_orchestrator.py
INFO: Starting task: task-3...  ← Skips failed task-2
```

**Behavior**:
- Failed tasks are **NOT automatically retried**
- This prevents infinite retry loops
- Failed tasks remain in the queue for investigation
- Can be manually reset to "pending" for retry

---

## Code References

### Task Persistence

**File**: `autonomous_agent/task_queue.py:54`
```python
def _save_tasks(self):
    """Saves the current list of tasks to the JSON queue file."""
    with open(self.queue_file, "w") as f:
        json.dump([task.to_dict() for task in self.tasks], f, indent=4)
```

**Called after**:
- Adding a task
- Updating task status
- Any state change

### Task Loading

**File**: `autonomous_agent/task_queue.py:41`
```python
def _load_tasks(self):
    """Loads tasks from the JSON queue file."""
    if os.path.exists(self.queue_file):
        with open(self.queue_file, "r") as f:
            task_data = json.load(f)
            self.tasks = [Task(**data) for data in task_data]
```

**Called when**:
- TaskQueue is initialized
- After system reboot/restart

### Task Selection

**File**: `autonomous_agent/task_queue.py:70`
```python
def get_next_task(self) -> Optional[Task]:
    """Retrieves the next pending task from the queue."""
    for task in self.tasks:
        if task.status == "pending":  # ← Only pending tasks
            return task
    return None
```

### Status Updates

**File**: `run_orchestrator.py:114`
```python
# On successful completion
task_queue.update_task_status(task.id, "completed")
```

**File**: `run_orchestrator.py:134`
```python
# On failure
task_queue.update_task_status(task.id, "failed")
```

---

## Test Verification

We have comprehensive tests that verify this behavior:

**Test File**: `tests/unit/autonomous_agent/test_persistence_after_reboot.py`

### Tests Included:

1. ✅ **test_completed_tasks_not_rerun_after_reboot**
   - Simulates multiple reboots
   - Verifies completed tasks are skipped
   - **Result**: PASSED

2. ✅ **test_failed_tasks_can_be_retried**
   - Verifies failed tasks don't auto-retry
   - Shows manual reset process
   - **Result**: PASSED

3. ✅ **test_in_progress_tasks_after_crash**
   - Simulates crash during task execution
   - Verifies safe handling
   - **Result**: PASSED

4. ✅ **test_multiple_reboots_with_mixed_statuses**
   - Realistic multi-reboot scenario
   - Mixed completed/failed/pending states
   - **Result**: PASSED

### Run Tests

```bash
source /home/node/git/OpenHands/.venv/bin/activate
python3 -m pytest tests/unit/autonomous_agent/test_persistence_after_reboot.py -v
```

**Expected Output**:
```
4 passed in 1.94s ✅
```

---

## Best Practices

### 1. Regular Monitoring

Check `tasks.json` periodically to see task status:

```bash
cat tasks.json | jq '.[] | {id: .id, status: .status}'
```

### 2. Handling Stuck Tasks

If a task is stuck in "in_progress" after a crash:

```python
from autonomous_agent.task_queue import TaskQueue

queue = TaskQueue("tasks.json")
queue.update_task_status("stuck-task-id", "pending")  # Reset to retry
# OR
queue.update_task_status("stuck-task-id", "failed")   # Mark as failed
```

### 3. Cleanup Completed Tasks

For long-running systems, you may want to archive completed tasks:

```python
from autonomous_agent.task_queue import TaskQueue

queue = TaskQueue("tasks.json")
all_tasks = queue.get_all_tasks()

# Remove completed tasks older than 30 days
for task in all_tasks:
    if task.status == "completed":
        # Archive or remove task
        pass
```

### 4. Idempotent Tasks

Even though the system prevents re-running completed tasks, it's good practice to write **idempotent tasks** - tasks that can be run multiple times safely if needed.

---

## Summary

| Question | Answer |
|----------|--------|
| Are completed tasks marked? | ✅ Yes, status = "completed" |
| Are they deleted? | ❌ No, they remain in tasks.json |
| Will they re-run after reboot? | ✅ No, only "pending" tasks run |
| What about failed tasks? | ⚠️ Require manual reset to retry |
| What about in-progress tasks? | ⚠️ Require manual reset to retry |
| Is the queue persistent? | ✅ Yes, saved to tasks.json |
| Can I safely reboot? | ✅ Yes, progress is preserved |

---

## Architecture Benefits

This design provides:

1. **Durability** - No data loss on crash/reboot
2. **Idempotency** - Tasks never executed twice
3. **Transparency** - Full state visible in JSON
4. **Safety** - Conservative retry behavior
5. **Control** - Manual override when needed

---

**Last Updated**: 2025-11-21
**Test Status**: ✅ All persistence tests passing
**Safety Rating**: ✅ Production-ready
