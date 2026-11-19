from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from gitjournal.assemble import RepoDay, build_user_message

OUTPUT_RESERVE = 64_000
CHARS_PER_TOKEN = 2

TokenCounter = Callable[[str, str], int]


class BudgetError(Exception):
    pass


@dataclass
class Call:
    user: str
    reduced: list[str] = field(default_factory=list)
    tokens: int = 0


def input_budget(context_limit: int, max_input_tokens: int) -> int:
    return max_input_tokens if max_input_tokens > 0 else context_limit - OUTPUT_RESERVE


def char_estimate(system: str, user: str) -> int:
    return (len(system) + len(user)) // CHARS_PER_TOKEN


def _reduce_repo(
    d: date,
    repo: RepoDay,
    quiet: list[RepoDay],
    omit: list[str],
    system: str,
    count: TokenCounter,
    budget: int,
) -> Call:
    candidates = sorted(
        ((len(f.patch), c.commit, f) for c in repo.commits for f in c.files),
        key=lambda t: t[0],
        reverse=True,
    )
    reduced: set[tuple[str, str]] = set()
    labels: list[str] = []
    while True:
        user = build_user_message(d, [repo, *quiet], omit, reduced)
        tokens = count(system, user)
        if tokens <= budget:
            return Call(user, labels, tokens)
        if not candidates:
            raise BudgetError(f"repo {repo.name} does not fit in {budget} tokens after reduction")
        overflow_chars = (tokens - budget) * CHARS_PER_TOKEN
        dropped = 0
        while candidates and dropped < overflow_chars:
            size, commit, f = candidates.pop(0)
            reduced.add((commit.sha, f.path))
            labels.append(f"{repo.name}: {f.path} ({commit.short})")
            dropped += size


def plan_calls(
    d: date,
    repos: list[RepoDay],
    omit: list[str],
    system: str,
    count: TokenCounter,
    budget: int,
) -> list[Call]:
    whole = build_user_message(d, repos, omit)
    tokens = count(system, whole)
    if tokens <= budget:
        return [Call(whole, tokens=tokens)]

    active = [r for r in repos if r.commits]
    quiet = [r for r in repos if not r.commits]
    calls = []
    for i, repo in enumerate(active):
        tail = quiet if i == len(active) - 1 else []
        calls.append(_reduce_repo(d, repo, tail, omit, system, count, budget))
    return calls
