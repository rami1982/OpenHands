"""Tests for the GitWorkspace class."""
import os
import tempfile
import shutil
from pathlib import Path
import pytest
from git import Repo

from autonomous_agent.workspace import GitWorkspace


class TestGitWorkspace:
    """Tests for the GitWorkspace class."""

    @pytest.fixture
    def temp_git_repo(self):
        """Create a temporary git repository for testing."""
        temp_dir = tempfile.mkdtemp()
        repo = Repo.init(temp_dir)

        # Create initial commit
        test_file = os.path.join(temp_dir, "README.md")
        with open(test_file, 'w') as f:
            f.write("# Test Repository\n")

        repo.index.add(["README.md"])
        repo.index.commit("Initial commit")

        yield temp_dir, repo

        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_init_valid_repo(self, temp_git_repo):
        """Test initializing workspace with a valid git repo."""
        temp_dir, _ = temp_git_repo
        workspace = GitWorkspace(repo_path=temp_dir)
        assert workspace.repo is not None
        assert workspace.original_branch.name in ["master", "main"]

    def test_init_invalid_repo(self):
        """Test that initializing with non-git directory raises error."""
        temp_dir = tempfile.mkdtemp()
        try:
            with pytest.raises(RuntimeError, match="not a valid Git repository"):
                GitWorkspace(repo_path=temp_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_create_new_branch(self, temp_git_repo):
        """Test creating a new branch."""
        temp_dir, _ = temp_git_repo
        workspace = GitWorkspace(repo_path=temp_dir)

        result = workspace.create_branch("test-branch")
        assert result is True
        assert workspace.repo.active_branch.name == "test-branch"

    def test_create_existing_branch(self, temp_git_repo):
        """Test creating a branch that already exists."""
        temp_dir, repo = temp_git_repo

        # Create a branch first
        repo.create_head("existing-branch")

        workspace = GitWorkspace(repo_path=temp_dir)
        result = workspace.create_branch("existing-branch")
        assert result is True
        assert workspace.repo.active_branch.name == "existing-branch"

    def test_add_all_and_commit(self, temp_git_repo):
        """Test adding and committing changes."""
        temp_dir, _ = temp_git_repo
        workspace = GitWorkspace(repo_path=temp_dir)
        workspace.create_branch("test-branch")

        # Make a change
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")

        workspace.add_all_and_commit("Add test file")

        # Check that commit was made
        latest_commit = workspace.repo.head.commit
        assert "Add test file" in latest_commit.message

    def test_commit_no_changes(self, temp_git_repo):
        """Test committing when there are no changes."""
        temp_dir, _ = temp_git_repo
        workspace = GitWorkspace(repo_path=temp_dir)
        workspace.create_branch("test-branch")

        # Try to commit without making changes
        # Should not raise an error
        workspace.add_all_and_commit("No changes")

    def test_checkout_original_branch(self, temp_git_repo):
        """Test checking out the original branch."""
        temp_dir, _ = temp_git_repo
        workspace = GitWorkspace(repo_path=temp_dir)
        original_branch_name = workspace.original_branch.name

        workspace.create_branch("test-branch")
        assert workspace.repo.active_branch.name == "test-branch"

        workspace.checkout_original_branch()
        assert workspace.repo.active_branch.name == original_branch_name

    def test_reset_branch(self, temp_git_repo):
        """Test resetting the branch (requires remote, so this is a basic test)."""
        temp_dir, _ = temp_git_repo
        workspace = GitWorkspace(repo_path=temp_dir)
        original_branch = workspace.original_branch.name

        # This test is limited because we don't have a remote
        # We'll just verify it doesn't crash when switching back
        workspace.create_branch("test-branch")

        # Make a change
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test content")
        workspace.repo.index.add(["test.txt"])

        # Attempt reset (will fail without remote, but tests the flow)
        try:
            workspace.reset_branch()
        except Exception:
            # Expected to fail without a proper remote
            pass

        # Should at least check out original branch
        assert workspace.repo.active_branch.name == original_branch
