import re

from git_summary.backends import RetryableError
from git_summary.budget import char_estimate

COMMIT_RE = re.compile(r'<commit sha="([0-9a-f]+)" author="([^"]*)"')
REPO_RE = re.compile(r'<repo name="([^"]+)"')


class FakeBackend:
    model = "fake-model"

    def __init__(self, skip=(), invent=None, flag=(), fail=False, context=1_000_000):
        self.skip = set(skip)
        self.invent = invent
        self.flag = set(flag)
        self.fail = fail
        self.context = context
        self.calls: list[tuple[str, str]] = []

    def summarise(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self.fail:
            raise RetryableError("fake outage")
        commits = [(s, a) for s, a in COMMIT_RE.findall(user) if s not in self.skip]
        repos = REPO_RE.findall(user)
        narrative = "\n".join(f"### {r}" for r in repos)
        narrative += "\n" + " ".join(f"Change [{s}]." for s, _ in commits)
        if self.invent:
            narrative += f" Invented [{self.invent}]."
        risks = [f"- Risky change by {a} [{s}]." for s, a in commits if s in self.flag]
        people = [f"- **{a}**: work [{s}]" for s, a in commits]
        return (
            f"<narrative>\n{narrative}\n</narrative>\n"
            f"<worth_a_look>\n{chr(10).join(risks) or 'Nothing flagged.'}\n</worth_a_look>\n"
            f"<people>\n{chr(10).join(people)}\n</people>\n"
        )

    def count_tokens(self, system: str, user: str) -> int:
        return char_estimate(system, user)

    def context_limit(self) -> int:
        return self.context
