from pathlib import Path

from git_summary.repos import FETCH_TIMEOUT, RepoError, run_git


class VaultError(Exception):
    pass


def _message(names: list[str]) -> str:
    days = sorted(Path(n).stem for n in names)
    span = days[0] if days[0] == days[-1] else f"{days[0]}..{days[-1]}"
    return f"git-summary: {span}"


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
        run_git(vault, "push", "-q", timeout=FETCH_TIMEOUT)
    except RepoError as e:
        raise VaultError(str(e)) from e
    return message
