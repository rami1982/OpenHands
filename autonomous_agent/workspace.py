import git
from git import Repo, GitCommandError

class GitWorkspace:
    """
    An abstraction layer over Git commands using GitPython.
    Handles creating/checking out branches, committing work, and resetting the workspace.
    """

    def __init__(self, repo_path: str = "."):
        """
        Initializes the GitWorkspace.

        Args:
            repo_path: The path to the git repository. Defaults to the current directory.
        """
        try:
            self.repo = Repo(repo_path, search_parent_directories=True)
            self.original_branch = self.repo.active_branch
        except git.InvalidGitRepositoryError:
            raise RuntimeError("The specified path is not a valid Git repository.")

    def create_branch(self, branch_name: str) -> bool:
        """
        Creates and checks out a new branch.

        Args:
            branch_name: The name of the branch to create.

        Returns:
            True if the branch was created successfully, False otherwise.
        """
        try:
            if branch_name in self.repo.heads:
                print(f"Branch '{branch_name}' already exists. Checking it out.")
                self.repo.heads[branch_name].checkout()
            else:
                self.repo.create_head(branch_name).checkout()
            print(f"Switched to new branch '{branch_name}'")
            return True
        except GitCommandError as e:
            print(f"Error creating branch '{branch_name}': {e}")
            return False

    def commit(self, message: str):
        """
        Commits all staged changes to the current branch.

        Args:
            message: The commit message.
        """
        try:
            if not self.repo.index.diff("HEAD"):
                print("No changes to commit.")
                return
            self.repo.index.commit(message)
            print(f"Committed changes with message: '{message}'")
        except GitCommandError as e:
            print(f"Error committing changes: {e}")
            raise

    def add_all_and_commit(self, message: str):
        """
        Adds all changes and commits them.

        Args:
            message: The commit message.
        """
        try:
            self.repo.git.add(A=True)
            self.commit(message)
        except GitCommandError as e:
            print(f"Error adding and committing changes: {e}")
            raise


    def reset_branch(self):
        """
        Resets the current branch to its original state (before any changes).
        It performs a hard reset to the original branch's HEAD.
        """
        try:
            print(f"Resetting branch to '{self.original_branch.name}'")
            self.repo.heads[self.original_branch.name].checkout(force=True)
            # The above line might be enough, but a hard reset is more thorough
            self.repo.git.reset('--hard', f'origin/{self.original_branch.name}')

        except GitCommandError as e:
            print(f"Error resetting branch: {e}")
            raise

    def checkout_original_branch(self):
        """
        Checks out the original branch that was active when the workspace was initialized.
        """
        try:
            self.original_branch.checkout()
            print(f"Switched back to original branch '{self.original_branch.name}'")
        except GitCommandError as e:
            print(f"Error checking out original branch: {e}")
            raise
