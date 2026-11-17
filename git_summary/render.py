import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

TAGS = ("narrative", "worth_a_look", "people")
NOTHING_FLAGGED = "Nothing flagged."
EMPTY_BODY = "No commits on main in any repository."
BULLET_RE = re.compile(r"^[-*] ", re.MULTILINE)
PLAIN_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
COMMITS_RE = re.compile(r"^commits:\s*(\d+)\s*$", re.MULTILINE)


class ResponseError(Exception):
    pass


@dataclass(frozen=True)
class Parsed:
    narrative: str
    worth_a_look: str
    people: str


@dataclass(frozen=True)
class PageMeta:
    date: date
    status: str
    repos: list[str]
    repos_missing: list[str]
    commits: int
    authors: list[str]
    risk_flags: int
    model: str
    generated_at: datetime


def parse_response(text: str) -> Parsed:
    parts = {}
    for tag in TAGS:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
        if not m:
            raise ResponseError(f"response is missing <{tag}>")
        parts[tag] = m.group(1).strip()
    return Parsed(**parts)


def count_risk_flags(worth_a_look: str) -> int:
    return len(BULLET_RE.findall(worth_a_look))


def merge_parsed(parts: list[Parsed]) -> Parsed:
    risks = [p.worth_a_look for p in parts if p.worth_a_look != NOTHING_FLAGGED]
    return Parsed(
        narrative="\n\n".join(p.narrative for p in parts),
        worth_a_look="\n".join(risks) or NOTHING_FLAGGED,
        people="\n".join(p.people for p in parts),
    )


def title(d: date) -> str:
    return f"# Git summary: {d:%A} {d.day} {d:%B %Y}"


def _flow(items: list[str]) -> str:
    return "[" + ", ".join(i if PLAIN_RE.match(i) else json.dumps(i) for i in items) + "]"


def frontmatter(m: PageMeta) -> str:
    return (
        "---\n"
        f"date: {m.date.isoformat()}\n"
        f"status: {m.status}\n"
        f"repos: {_flow(m.repos)}\n"
        f"repos_missing: {_flow(m.repos_missing)}\n"
        f"commits: {m.commits}\n"
        f"authors: {json.dumps(m.authors, ensure_ascii=False)}\n"
        f"risk_flags: {m.risk_flags}\n"
        f"model: {m.model}\n"
        f"generated_at: {m.generated_at.isoformat()}\n"
        "tags: [git-summary]\n"
        "---\n"
    )


def _callout(d: date, missing: dict[str, str]) -> str:
    lines = ["> [!warning] Partial page: some repositories could not be read"]
    lines += [f"> - **{name}**: {error}" for name, error in missing.items()]
    lines.append(f"> Regenerate with: `git-summary run --date {d.isoformat()} --force`")
    return "\n".join(lines) + "\n\n"


def _reduced_note(reduced: list[str]) -> str:
    lines = ["> [!note] Patches reduced to fit the model's context"]
    lines += [f"> - {r}" for r in reduced]
    return "\n".join(lines) + "\n\n"


def _head(m: PageMeta, missing: dict[str, str]) -> str:
    head = frontmatter(m) + "\n" + title(m.date) + "\n\n"
    if missing:
        head += _callout(m.date, missing)
    return head


def render_page(
    m: PageMeta,
    parsed: Parsed,
    missing: dict[str, str],
    reduced: list[str],
    not_mentioned: str | None,
) -> str:
    page = _head(m, missing)
    if reduced:
        page += _reduced_note(reduced)
    page += f"## Worth a look\n\n{parsed.worth_a_look}\n\n"
    page += f"## Details\n\n{parsed.narrative}\n\n"
    page += f"## People\n\n{parsed.people}\n"
    if not_mentioned:
        page += f"\n{not_mentioned}\n"
    return page


def render_empty_page(m: PageMeta, missing: dict[str, str]) -> str:
    return _head(m, missing) + EMPTY_BODY + "\n"


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_commit_count(path: Path) -> int | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    m = COMMITS_RE.search(text[4:end] if end != -1 else "")
    return int(m.group(1)) if m else None
