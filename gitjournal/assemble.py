from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from fnmatch import fnmatchcase
from html import escape

from gitjournal.repos import Commit, FileChange


@dataclass
class CommitData:
    commit: Commit
    files: list[FileChange] = field(default_factory=list)


@dataclass
class RepoDay:
    name: str
    web_url: str | None
    commits: list[CommitData] = field(default_factory=list)


def area_of(path: str) -> str:
    head, sep, _ = path.partition("/")
    return head if sep else "(root)"


def commit_areas(c: CommitData) -> list[str]:
    areas = set()
    for f in c.files:
        areas.add(area_of(f.path))
        if f.old_path:
            areas.add(area_of(f.old_path))
    return sorted(areas)


def is_omitted(path: str, patterns: list[str]) -> bool:
    candidates = (path, "./" + path)
    return any(fnmatchcase(p, pat) for pat in patterns for p in candidates)


def _numstat_line(f: FileChange) -> str:
    name = f"{f.old_path} => {f.path}" if f.old_path else f.path
    if f.binary:
        return f"-\t-\t{name}"
    return f"{f.added}\t{f.deleted}\t{name}"


def _file_patch(c: CommitData, f: FileChange, omit: list[str], reduced: set) -> str:
    if (c.commit.sha, f.path) in reduced:
        return f"[patch reduced to fit context: {f.path}, +{f.added} -{f.deleted}]\n"
    if is_omitted(f.path, omit):
        return f"[patch omitted: {f.path}, +{f.added} -{f.deleted}]\n"
    return f.patch if f.patch.endswith("\n") else f.patch + "\n"


def render_commit(c: CommitData, omit: list[str], reduced: set | None = None) -> str:
    reduced = reduced or set()
    commit = c.commit
    message = commit.subject + (f"\n\n{commit.body}" if commit.body else "")
    when = commit.committed.strftime("%Y-%m-%d %H:%M %Z")
    numstat = "\n".join(_numstat_line(f) for f in c.files)
    patch = "".join(_file_patch(c, f, omit, reduced) for f in c.files)
    return (
        f'<commit sha="{commit.short}" author="{escape(commit.author)}" time="{when}">\n'
        f"<message>\n{message}\n</message>\n"
        f"<areas>{', '.join(commit_areas(c))}</areas>\n"
        f"<numstat>\n{numstat}\n</numstat>\n"
        f"<patch>\n{patch}</patch>\n"
        f"</commit>\n"
    )


def area_counts(repo: RepoDay) -> str:
    counts = Counter(a for c in repo.commits for a in commit_areas(c))
    return ", ".join(f"{a}: {n}" for a, n in counts.most_common())


def render_repo(repo: RepoDay, omit: list[str], reduced: set | None = None) -> str:
    commits = "".join(render_commit(c, omit, reduced) for c in repo.commits)
    return (
        f'<repo name="{escape(repo.name)}" web_url="{escape(repo.web_url or "")}" '
        f'commits="{len(repo.commits)}">\n'
        f"<area_counts>{area_counts(repo)}</area_counts>\n"
        f"{commits}</repo>\n"
    )


def build_user_message(
    d: date, repos: list[RepoDay], omit: list[str], reduced: set | None = None
) -> str:
    parts = [f"Date: {d.isoformat()} ({d.strftime('%A')})\n"]
    parts += [render_repo(r, omit, reduced) for r in repos if r.commits]
    quiet = [r.name for r in repos if not r.commits]
    if quiet:
        parts.append(f"Repositories with no commits on this day: {', '.join(quiet)}\n")
    return "\n".join(parts)
