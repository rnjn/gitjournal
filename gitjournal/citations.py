import re
from dataclasses import dataclass

from gitjournal.repos import Commit

SHA = r"[0-9a-f]{7,40}"
MARKER_RE = re.compile(rf"\[({SHA}(?:\s*,\s*{SHA})*)\](?!\()")


@dataclass(frozen=True)
class Cited:
    repo: str
    web_url: str | None
    commit: Commit


def _link(marker: str, c: Cited) -> str:
    if not c.web_url:
        return f"`{marker}`"
    return f"[{marker}]({c.web_url}/commit/{c.commit.sha})"


def _resolve(marker: str, known: list[Cited]) -> Cited | None:
    matches = [c for c in known if c.commit.sha.startswith(marker)]
    return matches[0] if len(matches) == 1 else None


def link_citations(text: str, known: list[Cited]) -> tuple[str, set[str], list[str]]:
    cited: set[str] = set()
    unknown: list[str] = []

    def replace(m: re.Match) -> str:
        markers = [s.strip() for s in m.group(1).split(",")]
        out = []
        for marker in markers:
            hit = _resolve(marker, known)
            if hit is None:
                unknown.append(marker)
                out.append(f"[{marker}]")
            else:
                cited.add(hit.commit.sha)
                out.append(_link(marker, hit))
        return ", ".join(out)

    return MARKER_RE.sub(replace, text), cited, unknown


def not_mentioned_line(known: list[Cited], cited: set[str]) -> str | None:
    missing = [c for c in known if c.commit.sha not in cited]
    if not missing:
        return None
    items = [f"{_link(c.commit.short, c)} {c.commit.subject} ({c.repo})" for c in missing]
    return "Not mentioned above: " + "; ".join(items)
