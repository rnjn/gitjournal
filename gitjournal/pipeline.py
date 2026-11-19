import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from gitjournal.assemble import CommitData, RepoDay
from gitjournal.backends import Backend, BackendError, with_retries
from gitjournal.budget import BudgetError, input_budget, plan_calls
from gitjournal.citations import Cited, link_citations, not_mentioned_line
from gitjournal.config import Config, load_system_prompt
from gitjournal.days import page_path, recent_pages
from gitjournal.render import (
    PageMeta,
    Parsed,
    ResponseError,
    count_risk_flags,
    merge_parsed,
    parse_response,
    read_commit_count,
    render_empty_page,
    render_page,
    write_atomic,
)
from gitjournal.repos import (
    RepoError,
    commit_files,
    commits_for_day,
    detect_branch,
    prepare,
    web_url,
)

LATE_CHECK_PAGES = 3


@dataclass(frozen=True)
class RepoState:
    name: str
    gitdir: Path
    branch: str
    web_url: str | None


@dataclass
class DayResult:
    day: date
    outcome: str
    commits: int = 0
    tokens: int = 0
    calls: int = 0
    error: str | None = None


class Pipeline:
    def __init__(
        self,
        cfg: Config,
        backend: Backend,
        log: logging.Logger,
        now: datetime,
        dry_run: bool = False,
        save_prompts: Path | None = None,
    ):
        self.cfg = cfg
        self.backend = backend
        self.log = log
        self.now = now
        self.dry_run = dry_run
        self.save_prompts = save_prompts
        self.repos: list[RepoState] = []
        self.fetch_errors: dict[str, str] = {}
        self._system: str | None = None
        self._budget: int | None = None

    def fetch_all(self) -> None:
        for repo in self.cfg.repos:
            try:
                gitdir = prepare(repo, self.cfg.cache_dir)
                state = RepoState(
                    repo.name,
                    gitdir,
                    detect_branch(gitdir, repo.branch),
                    web_url(gitdir, repo.web_url),
                )
                self.repos.append(state)
                self.log.info("fetch %s ok branch=%s", repo.name, state.branch)
            except RepoError as e:
                self.fetch_errors[repo.name] = str(e)
                self.log.error("fetch %s failed: %s", repo.name, e)

    def read_day(self, d: date) -> tuple[list[RepoDay], dict[str, str]]:
        missing = dict(self.fetch_errors)
        days = []
        for state in self.repos:
            try:
                commits = commits_for_day(state.gitdir, state.branch, d, self.cfg.tz)
                data = [CommitData(c, commit_files(state.gitdir, c.sha)) for c in commits]
                days.append(RepoDay(state.name, state.web_url, data))
            except RepoError as e:
                missing[state.name] = str(e)
                self.log.error("%s read %s failed: %s", d, state.name, e)
        order = {r.name: i for i, r in enumerate(self.cfg.repos)}
        missing = dict(sorted(missing.items(), key=lambda kv: order[kv[0]]))
        return days, missing

    def check_late_commits(self, skip: set[date]) -> None:
        if self.fetch_errors:
            return
        for d in recent_pages(self.cfg.output_dir, LATE_CHECK_PAGES):
            if d in skip:
                continue
            recorded = read_commit_count(page_path(self.cfg.output_dir, d))
            if recorded is None:
                continue
            days, missing = self.read_day(d)
            if missing:
                continue
            actual = sum(len(r.commits) for r in days)
            if actual != recorded:
                self.log.warning(
                    "%s page records %d commits but main now has %d; "
                    "regenerate with: gitjournal run --date %s --force",
                    d,
                    recorded,
                    actual,
                    d,
                )

    @property
    def system(self) -> str:
        if self._system is None:
            self._system = load_system_prompt(self.cfg.config_dir)
        return self._system

    @property
    def budget(self) -> int:
        if self._budget is None:
            limit = 0 if self.cfg.model.max_input_tokens else self.backend.context_limit()
            self._budget = input_budget(limit, self.cfg.model.max_input_tokens)
        return self._budget

    def _meta(self, d, status, days, missing, commits, risk_flags) -> PageMeta:
        authors = sorted({c.commit.author for r in days for c in r.commits})
        return PageMeta(
            date=d,
            status=status,
            repos=[r.name for r in days],
            repos_missing=list(missing),
            commits=commits,
            authors=authors,
            risk_flags=risk_flags,
            model=self.backend.model,
            generated_at=self.now.astimezone(self.cfg.tz).replace(microsecond=0),
        )

    def _save(self, d: date, n: int, kind: str, text: str) -> None:
        if self.save_prompts is None:
            return
        self.save_prompts.mkdir(parents=True, exist_ok=True)
        ext = "md" if kind == "system" else "txt"
        (self.save_prompts / f"{d}-call{n}-{kind}.{ext}").write_text(text, encoding="utf-8")

    def _call(self, d: date, n: int, user: str) -> Parsed:
        self._save(d, n, "system", self.system)
        self._save(d, n, "user", user)

        def attempt() -> Parsed:
            raw = self.backend.summarise(self.system, user)
            self._save(d, n, "response", raw)
            return parse_response(raw)

        return with_retries(attempt)

    def generate(self, d: date) -> DayResult:
        days, missing = self.read_day(d)
        if not days:
            return DayResult(d, "failed", error="no repository could be read")
        commits = sum(len(r.commits) for r in days)
        status = "partial" if missing else "ok"

        if commits == 0:
            if not self.dry_run:
                meta = self._meta(d, "partial" if missing else "empty", days, missing, 0, 0)
                write_atomic(page_path(self.cfg.output_dir, d), render_empty_page(meta, missing))
            return DayResult(d, "partial" if missing else "empty")

        try:
            calls = plan_calls(
                d,
                days,
                self.cfg.omit_patch,
                self.system,
                lambda s, u: with_retries(lambda: self.backend.count_tokens(s, u)),
                self.budget,
            )
        except (BudgetError, BackendError) as e:
            return DayResult(d, "failed", commits, error=str(e))
        tokens = sum(c.tokens for c in calls)
        if len(calls) > 1:
            self.log.info("%s split into %d calls to fit the context budget", d, len(calls))
        if self.dry_run:
            return DayResult(d, "dry-run", commits, tokens, 0)

        try:
            parts = [self._call(d, i + 1, c.user) for i, c in enumerate(calls)]
        except (BackendError, ResponseError) as e:
            return DayResult(d, "failed", commits, tokens, len(calls), str(e))
        merged = parts[0] if len(parts) == 1 else merge_parsed(parts)

        known = [Cited(r.name, r.web_url, c.commit) for r in days for c in r.commits]
        cited: set[str] = set()
        unknown: list[str] = []
        linked = []
        for text in (merged.narrative, merged.worth_a_look, merged.people):
            out, hits, bad = link_citations(text, known)
            linked.append(out)
            cited |= hits
            unknown += bad
        if unknown:
            self.log.warning("%s model cited unknown SHAs: %s", d, ", ".join(unknown))
        missing_cites = not_mentioned_line(known, cited)
        if missing_cites:
            self.log.warning("%s %d commits not cited by the model", d, len(known) - len(cited))

        parsed = Parsed(*linked)
        reduced = [label for c in calls for label in c.reduced]
        meta = self._meta(d, status, days, missing, commits, count_risk_flags(parsed.worth_a_look))
        page = render_page(meta, parsed, missing, reduced, missing_cites)
        write_atomic(page_path(self.cfg.output_dir, d), page)
        return DayResult(d, status, commits, tokens, len(calls))
