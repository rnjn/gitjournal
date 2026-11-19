import contextlib
from pathlib import Path

from gitjournal.repos import FETCH_TIMEOUT, RepoError, run_git


class VaultError(Exception):
    pass


def _message(names: list[str]) -> str:
    days = sorted(Path(n).stem for n in names)
    span = days[0] if days[0] == days[-1] else f"{days[0]}..{days[-1]}"
    return f"gitjournal: {span}"


def publish(vault: Path, folder: str) -> str | None:
    try:
        run_git(vault, "rev-parse", "--show-toplevel")
    except RepoError as e:
        raise VaultError(f"{vault} is not a git repository") from e

    message = None
    try:
        run_git(vault, "add", "-A", "--", folder)
        staged = run_git(vault, "diff", "--cached", "--name-only", "-z", "--", folder)
        names = [n for n in staged.split("\0") if n]
        if names:
            message = _message(names)
            run_git(vault, "commit", "-q", "-m", message, "--", folder)
    except RepoError as e:
        raise VaultError(str(e)) from e

    try:
        run_git(vault, "pull", "--rebase", "--autostash", "-q", timeout=FETCH_TIMEOUT)
    except RepoError as e:
        with contextlib.suppress(RepoError):
            run_git(vault, "rebase", "--abort")
        raise VaultError(f"git pull --rebase failed: {e}") from e

    try:
        run_git(vault, "push", "-q", timeout=FETCH_TIMEOUT)
    except RepoError as e:
        raise VaultError(str(e)) from e
    return message
