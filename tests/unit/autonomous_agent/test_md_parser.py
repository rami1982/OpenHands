"""Tests for the markdown parser."""
import os
import tempfile
import shutil
import pytest

from autonomous_agent.parsers.md_parser import parse_markdown_files


class TestMarkdownParser:
    """Tests for the markdown file parser."""

    @pytest.fixture
    def temp_task_dir(self):
        """Create a temporary directory with markdown files."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_parse_empty_directory(self, temp_task_dir):
        """Test parsing an empty directory."""
        tasks = parse_markdown_files(temp_task_dir)
        assert len(tasks) == 0

    def test_parse_nonexistent_directory(self):
        """Test parsing a directory that doesn't exist."""
        tasks = parse_markdown_files("/nonexistent/directory")
        assert len(tasks) == 0

    def test_parse_single_markdown_file(self, temp_task_dir):
        """Test parsing a single markdown file."""
        task_file = os.path.join(temp_task_dir, "task1.md")
        with open(task_file, 'w') as f:
            f.write("# Task 1\n\nThis is the first task.")

        tasks = parse_markdown_files(temp_task_dir)
        assert len(tasks) == 1
        assert tasks[0].description == "# Task 1\n\nThis is the first task."
        assert tasks[0].file_path == task_file
        assert tasks[0].status == "pending"

    def test_parse_multiple_markdown_files(self, temp_task_dir):
        """Test parsing multiple markdown files."""
        task1_file = os.path.join(temp_task_dir, "task1.md")
        task2_file = os.path.join(temp_task_dir, "task2.md")

        with open(task1_file, 'w') as f:
            f.write("Task 1 content")
        with open(task2_file, 'w') as f:
            f.write("Task 2 content")

        tasks = parse_markdown_files(temp_task_dir)
        assert len(tasks) == 2

        # Check that both tasks are present
        descriptions = [task.description for task in tasks]
        assert "Task 1 content" in descriptions
        assert "Task 2 content" in descriptions

    def test_parse_ignores_non_markdown_files(self, temp_task_dir):
        """Test that non-markdown files are ignored."""
        md_file = os.path.join(temp_task_dir, "task.md")
        txt_file = os.path.join(temp_task_dir, "notes.txt")
        py_file = os.path.join(temp_task_dir, "script.py")

        with open(md_file, 'w') as f:
            f.write("Task content")
        with open(txt_file, 'w') as f:
            f.write("Notes")
        with open(py_file, 'w') as f:
            f.write("print('hello')")

        tasks = parse_markdown_files(temp_task_dir)
        assert len(tasks) == 1
        assert tasks[0].description == "Task content"

    def test_task_id_is_stable(self, temp_task_dir):
        """Test that task IDs are stable (same file = same ID)."""
        task_file = os.path.join(temp_task_dir, "task1.md")
        with open(task_file, 'w') as f:
            f.write("Task content")

        tasks1 = parse_markdown_files(temp_task_dir)
        tasks2 = parse_markdown_files(temp_task_dir)

        assert tasks1[0].id == tasks2[0].id

    def test_task_id_is_unique_per_file(self, temp_task_dir):
        """Test that different files get different task IDs."""
        task1_file = os.path.join(temp_task_dir, "task1.md")
        task2_file = os.path.join(temp_task_dir, "task2.md")

        with open(task1_file, 'w') as f:
            f.write("Task 1")
        with open(task2_file, 'w') as f:
            f.write("Task 2")

        tasks = parse_markdown_files(temp_task_dir)
        assert tasks[0].id != tasks[1].id

    def test_parse_utf8_content(self, temp_task_dir):
        """Test parsing markdown files with UTF-8 content."""
        task_file = os.path.join(temp_task_dir, "unicode_task.md")
        with open(task_file, 'w', encoding='utf-8') as f:
            f.write("# 任务 (Task)\n\nこんにちは 🚀")

        tasks = parse_markdown_files(temp_task_dir)
        assert len(tasks) == 1
        assert "任务" in tasks[0].description
        assert "こんにちは" in tasks[0].description
        assert "🚀" in tasks[0].description
