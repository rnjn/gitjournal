import os
import subprocess
from pathlib import Path

BASE_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_COMMITTER_NAME": "Committer",
    "GIT_COMMITTER_EMAIL": "c@example.com",
}


def git(cwd: Path, *args: str, env: dict | None = None) -> str:
    full_env = {**os.environ, **BASE_ENV, **(env or {})}
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=full_env, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


class Repo:
    def __init__(self, path: Path, branch: str = "main"):
        self.path = path
        path.mkdir(parents=True)
        git(path, "init", "-q", "-b", branch)

    def commit(
        self,
        when: str,
        message: str = "change",
        files: dict[str, str | bytes | None] | None = None,
        author: str = "Asha Rao",
    ) -> str:
        for name, content in (files or {}).items():
            p = self.path / name
            if content is None:
                git(self.path, "rm", "-q", name)
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                p.write_bytes(content)
            else:
                p.write_text(content)
            git(self.path, "add", name)
        env = {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": "a@example.com",
            "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_DATE": when,
        }
        git(self.path, "commit", "-q", "--allow-empty", "-m", message, env=env)
        return git(self.path, "rev-parse", "HEAD")

    def clone_to(self, dest: Path) -> Path:
        git(dest.parent, "clone", "-q", str(self.path), dest.name)
        return dest
