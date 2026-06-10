import re
import subprocess
from pathlib import Path
from typing import List, Optional, Union


_SPLIT_VMDK_PART_RE = re.compile(r"s\d{3}\.vmdk$", re.IGNORECASE)


def _is_split_vmdk_part(path: Path) -> bool:
    """
    Check whether a VMDK file is a split disk data part.

    Args:
        path: VMDK path.

    Returns:
        True if the file name ends with sNNN.vmdk, otherwise False.
    """
    return bool(_SPLIT_VMDK_PART_RE.search(path.name))


def _git_path(path: Path, root: Path) -> str:
    """
    Convert a file path to a path suitable for git commands.

    Args:
        path: File path.
        root: Git command working directory.

    Returns:
        Relative path when possible, otherwise the original path.
    """
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _ensure_git_repo(d: Path, git: str) -> None:
    """
    Ensure a directory is inside a git repository.

    Args:
        d: Directory to check.
        git: Git executable.

    Returns:
        None
    """
    try:
        subprocess.run(
            [git, "status"],
            check=True,
            cwd=d,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{d} 不是一个 git 仓库") from e


def find_git_files(d: Union[str, Path], include_split_vmdk_parts: bool = False) -> List[Path]:
    """
    Find VMware files that should be tracked by git.

    Args:
        d: VMware directory.
        include_split_vmdk_parts: Whether to include split VMDK data parts
            ending with sNNN.vmdk.

    Returns:
        VMware files to track in git.
    """
    root = Path(d)
    files = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        suffix = path.suffix.casefold()
        if suffix == ".vmx":
            files.append(path)
        elif suffix == ".vmdk" and (include_split_vmdk_parts or not _is_split_vmdk_part(path)):
            files.append(path)

    return sorted(files, key=lambda p: str(p).casefold())


def sync_to_git(
        d: Union[str, Path],
        commit_message: Optional[str] = None,
        commit: bool = True,
        include_split_vmdk_parts: bool = False,
        git: str = "git",
        verbose: bool = True,
        ) -> List[Path]:
    """
    Sync important VMware files into git and optionally create a commit.

    Args:
        d: VMware directory inside a git repository.
        commit_message: Commit message; defaults to "sync vmware files".
        commit: Whether to commit staged changes after adding files.
        include_split_vmdk_parts: Whether to include split VMDK data parts
            ending with sNNN.vmdk.
        git: Git executable.
        verbose: Whether to print a message when there is nothing to commit.

    Returns:
        Files passed to git add.
    """
    root = Path(d)
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    _ensure_git_repo(root, git)

    files = find_git_files(root, include_split_vmdk_parts=include_split_vmdk_parts)
    for file in files:
        subprocess.run([git, "add", _git_path(file, root)], check=True, cwd=root)

    if not commit:
        return files

    result = subprocess.run([git, "diff", "--cached", "--quiet"], cwd=root)
    if result.returncode == 0:
        if verbose:
            print("没有文件产生更改，无需 commit")
        return files
    if result.returncode != 1:
        raise subprocess.CalledProcessError(result.returncode, [git, "diff", "--cached", "--quiet"])

    if commit_message is None:
        commit_message = "sync vmware files"

    subprocess.run([git, "commit", "-m", commit_message], check=True, cwd=root)
    return files


__all__ = [
    "find_git_files",
    "sync_to_git",
]
