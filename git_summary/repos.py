import os
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from git_summary.config import RepoConfig
from git_summary.days import day_bounds

FETCH_TIMEOUT = 120
GIT_TIMEOUT = 60
LOG_FORMAT = "%H%x00%h%x00%an%x00%cI%x00%s%x00%b%x1e"
DIFF_ARGS = ["--format=", "--no-color", "-M", "--diff-merges=first-parent"]


class RepoError(Exception):
    pass


@dataclass(frozen=True)
class Commit:
    sha: str
    short: str
    author: str
    committed: datetime
    subject: str
    body: str


@dataclass(frozen=True)
class FileChange:
    path: str
    old_path: str | None
    added: int
    deleted: int
    binary: bool
    patch: str


def run_git(cwd: Path, *args: str, timeout: int = GIT_TIMEOUT) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        out = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RepoError(f"git {args[0]} timed out after {timeout}s") from e
    except OSError as e:
        raise RepoError(f"git {args[0]} failed: {e}") from e
    if out.returncode != 0:
        err = out.stderr.decode("utf-8", "replace").strip()
        raise RepoError(f"git {args[0]} failed: {err}")
    return out.stdout.decode("utf-8", "replace")


def prepare(repo: RepoConfig, cache_dir: Path) -> Path:
    if repo.path is not None:
        if not (repo.path / ".git").exists() and not repo.path.is_dir():
            raise RepoError(f"path not found: {repo.path}")
        run_git(repo.path, "fetch", "-q", "--prune", "origin", timeout=FETCH_TIMEOUT)
        return repo.path

    dest = cache_dir / f"{repo.name}.git"
    if not dest.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        run_git(cache_dir, "clone", "-q", "--bare", repo.url, dest.name, timeout=FETCH_TIMEOUT)
        run_git(dest, "config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")
        run_git(dest, "fetch", "-q", "--prune", "origin", timeout=FETCH_TIMEOUT)
        run_git(dest, "remote", "set-head", "origin", "--auto", timeout=FETCH_TIMEOUT)
    else:
        run_git(dest, "fetch", "-q", "--prune", "origin", timeout=FETCH_TIMEOUT)
    return dest


def _has_ref(gitdir: Path, ref: str) -> bool:
    try:
        run_git(gitdir, "rev-parse", "--verify", "-q", ref)
        return True
    except RepoError:
        return False


def detect_branch(gitdir: Path, override: str | None) -> str:
    if override:
        return override
    try:
        head = run_git(gitdir, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").strip()
        return head.removeprefix("origin/")
    except RepoError:
        pass
    for candidate in ("main", "master"):
        if _has_ref(gitdir, f"refs/remotes/origin/{candidate}"):
            return candidate
    raise RepoError("cannot detect default branch: no origin/HEAD, origin/main or origin/master")


SCP_RE = re.compile(r"^[\w.-]+@([^:/]+):(.+)$")
URL_RE = re.compile(r"^(?:ssh|https?|git)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$")


def derive_web_url(remote_url: str) -> str | None:
    m = SCP_RE.match(remote_url) or URL_RE.match(remote_url)
    if not m:
        return None
    host, path = m.groups()
    path = path.rstrip("/").removesuffix(".git")
    return f"https://{host}/{path}"


def web_url(gitdir: Path, override: str | None) -> str | None:
    if override:
        return override.rstrip("/")
    try:
        return derive_web_url(run_git(gitdir, "remote", "get-url", "origin").strip())
    except RepoError:
        return None


def _git_date(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S %z")


def commits_for_day(gitdir: Path, branch: str, d: date, tz: ZoneInfo) -> list[Commit]:
    start, end = day_bounds(d, tz)
    out = run_git(
        gitdir,
        "log",
        f"refs/remotes/origin/{branch}",
        "--first-parent",
        "--reverse",
        f"--since-as-filter={_git_date(start - timedelta(days=1))}",
        f"--until={_git_date(end + timedelta(days=1))}",
        f"--format={LOG_FORMAT}",
    )
    commits = []
    for record in out.split("\x1e"):
        record = record.lstrip("\n")
        if not record:
            continue
        sha, short, author, committed, subject, body = record.split("\x00", 5)
        when = datetime.fromisoformat(committed)
        if start <= when < end:
            commits.append(
                Commit(sha, short, author, when.astimezone(tz), subject, body.strip("\n"))
            )
    return commits


def _parse_numstat(out: str) -> list[tuple[str, str | None, int, int, bool]]:
    tokens = out.split("\x00")
    entries = []
    i = 0
    while i < len(tokens):
        head = tokens[i].lstrip("\n")
        if not head:
            i += 1
            continue
        added, deleted, path = head.split("\t", 2)
        old_path = None
        if path == "":
            old_path, path = tokens[i + 1], tokens[i + 2]
            i += 3
        else:
            i += 1
        binary = added == "-"
        entries.append(
            (path, old_path, 0 if binary else int(added), 0 if binary else int(deleted), binary)
        )
    return entries


def _split_patch(out: str) -> list[str]:
    chunks = re.split(r"(?m)^(?=diff --git )", out)
    return [c for c in chunks if c.startswith("diff --git ")]


def commit_files(gitdir: Path, sha: str) -> list[FileChange]:
    numstat = _parse_numstat(run_git(gitdir, "show", *DIFF_ARGS, "--numstat", "-z", sha))
    patches = _split_patch(run_git(gitdir, "show", *DIFF_ARGS, "--patch", sha))
    if len(patches) != len(numstat):
        raise RepoError(f"{sha[:12]}: numstat and patch disagree on file count")
    return [
        FileChange(path, old, added, deleted, binary, patch)
        for (path, old, added, deleted, binary), patch in zip(numstat, patches, strict=True)
    ]
