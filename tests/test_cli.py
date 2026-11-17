import fcntl
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from git_summary import cli
from tests.fakes import FakeBackend
from tests.gitutil import Repo, git

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=IST)


class Env:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.vault = tmp_path / "vault"
        self.vault.mkdir()
        self.out = self.vault / "Git Summary"
        self.log = tmp_path / "state" / "git-summary.log"
        self.code = Repo(tmp_path / "remotes" / "code")
        self.docs = Repo(tmp_path / "remotes" / "docs")
        self.code.commit("2026-10-01T10:00:00+05:30", "initial", {"src/app.py": "a\n"})
        self.docs.commit("2026-10-01T10:00:00+05:30", "initial", {"index.md": "a\n"})
        self.backend = FakeBackend()
        self.extra = ""
        self.repo_urls = {"code": str(self.code.path), "docs": str(self.docs.path)}

    @property
    def config(self):
        repos = "".join(
            f'[[repos]]\nname = "{n}"\nurl = "{u}"\nweb_url = "https://github.com/org/{n}"\n'
            for n, u in self.repo_urls.items()
        )
        path = self.tmp / "config" / "config.toml"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            f'vault_path = "{self.vault}"\n'
            f'cache_dir = "{self.tmp / "cache"}"\n'
            f'log_file = "{self.log}"\n'
            f"{self.extra}\n{repos}"
        )
        return path

    def run(self, *args, backend=None):
        backend = backend or self.backend
        argv = ["--config", str(self.config), *args]
        return cli.main(argv, now=NOW, backend_factory=lambda model, override: backend)

    def page(self, d):
        return (self.out / f"{d}.md").read_text()

    def log_text(self):
        return self.log.read_text()


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_first_run_writes_thirty_pages_ending_yesterday(env):
    assert env.run("run") == 0
    pages = sorted(p.name for p in env.out.iterdir())
    assert len(pages) == 30
    assert pages[0] == "2026-10-17.md"
    assert pages[-1] == "2026-11-15.md"
    assert env.backend.calls == []


def test_empty_day_page(env):
    env.run("run", "--date", "2026-11-15")
    page = env.page("2026-11-15")
    assert "status: empty" in page
    assert "commits: 0" in page
    assert "repos: [code, docs]" in page
    assert page.rstrip().endswith("No commits on main in any repository.")
    assert env.backend.calls == []


def test_day_with_commits_full_page(env):
    a = env.code.commit("2026-11-15T09:00:00+05:30", "Add retries", {"src/app.py": "b\n"})
    b = env.code.commit(
        "2026-11-15T10:00:00+05:30", "Bump lock", {"package-lock.json": "{}\n"}, "dependabot[bot]"
    )
    c = env.docs.commit("2026-11-15T23:59:59+05:30", "Docs", {"index.md": "c\n"}, "Vikram N")
    env.docs.commit("2026-11-16T00:00:00+05:30", "Tomorrow", {"index.md": "d\n"})
    env.backend.flag = {a[:7]}

    assert env.run("run", "--date", "2026-11-15") == 0
    page = env.page("2026-11-15")

    assert "status: ok" in page
    assert "commits: 3" in page
    assert 'authors: ["Asha Rao", "Vikram N", "dependabot[bot]"]' in page
    assert "risk_flags: 1" in page
    assert "model: fake-model" in page
    assert page.count("## Details") == 1
    assert f"[{a[:7]}](https://github.com/org/code/commit/{a})" in page
    assert f"[{c[:7]}](https://github.com/org/docs/commit/{c})" in page
    assert "Tomorrow" not in env.backend.calls[0][1]
    [(system, user)] = env.backend.calls
    assert "Worth a look checklist" in system
    assert "0\t1\tpackage-lock.json" in user or "1\t0\tpackage-lock.json" in user
    assert "[patch omitted: package-lock.json" in user
    assert b[:7] in user


def test_second_run_is_a_no_op(env):
    env.code.commit("2026-11-15T09:00:00+05:30", "x", {"src/app.py": "b\n"})
    env.run("run")
    mtimes = {p: p.stat().st_mtime_ns for p in env.out.iterdir()}
    calls = len(env.backend.calls)
    assert env.run("run") == 0
    assert len(env.backend.calls) == calls
    assert {p: p.stat().st_mtime_ns for p in env.out.iterdir()} == mtimes


def test_deleted_page_is_regenerated_alone(env):
    env.run("run")
    (env.out / "2026-11-01.md").unlink()
    before = {p.name: p.stat().st_mtime_ns for p in env.out.iterdir()}
    env.run("run")
    after = {p.name: p.stat().st_mtime_ns for p in env.out.iterdir()}
    assert set(after) - set(before) == {"2026-11-01.md"}
    assert all(after[n] == t for n, t in before.items())


def test_force_requires_date_or_range(env):
    assert env.run("run", "--force") == 2


def test_force_overwrites_explicit_date(env):
    env.run("run", "--date", "2026-11-15")
    env.code.commit("2026-11-15T09:00:00+05:30", "late", {"src/app.py": "b\n"})
    assert env.run("run", "--date", "2026-11-15") == 0
    assert "commits: 0" in env.page("2026-11-15")
    assert env.run("run", "--date", "2026-11-15", "--force") == 0
    assert "commits: 1" in env.page("2026-11-15")


def test_range(env):
    assert env.run("run", "--from", "2026-11-01", "--to", "2026-11-03") == 0
    assert sorted(p.name for p in env.out.iterdir()) == [
        "2026-11-01.md",
        "2026-11-02.md",
        "2026-11-03.md",
    ]


def test_unreachable_repo_gives_partial_page(env):
    env.code.commit("2026-11-15T09:00:00+05:30", "x", {"src/app.py": "b\n"})
    env.repo_urls["sdk"] = str(env.tmp / "missing-remote")
    assert env.run("run", "--date", "2026-11-15") == 1
    page = env.page("2026-11-15")
    assert "status: partial" in page
    assert "repos: [code, docs]" in page
    assert "repos_missing: [sdk]" in page
    assert "**sdk**" in page
    assert "git-summary run --date 2026-11-15 --force" in page
    assert "sdk" in env.log_text()


def test_every_repo_failing_writes_nothing(env):
    env.repo_urls = {"a": str(env.tmp / "nope-a"), "b": str(env.tmp / "nope-b")}
    assert env.run("run", "--date", "2026-11-15") == 1
    assert not env.out.exists() or not any(env.out.iterdir())


def test_model_failure_writes_nothing_and_continues(env, monkeypatch):
    monkeypatch.setattr("git_summary.backends.BASE_DELAY", 0)
    env.code.commit("2026-11-14T09:00:00+05:30", "x", {"src/app.py": "b\n"})
    env.backend.fail = True
    assert env.run("run", "--from", "2026-11-13", "--to", "2026-11-15") == 1
    assert sorted(p.name for p in env.out.iterdir()) == ["2026-11-13.md", "2026-11-15.md"]
    assert len(env.backend.calls) == 3
    assert "2026-11-14" in env.log_text()


def test_invented_sha_unlinked_and_logged_uncited_listed(env):
    a = env.code.commit("2026-11-15T09:00:00+05:30", "Cited", {"src/app.py": "b\n"})
    b = env.code.commit("2026-11-15T10:00:00+05:30", "Forgotten", {"src/app.py": "c\n"})
    env.backend.skip = {b[:7]}
    env.backend.invent = "deadbee"
    env.run("run", "--date", "2026-11-15")
    page = env.page("2026-11-15")
    assert "Invented [deadbee]." in page
    assert "deadbee" in env.log_text()
    assert (
        f"Not mentioned above: [{b[:7]}](https://github.com/org/code/commit/{b}) Forgotten" in page
    )
    assert a[:7] in page


def test_over_budget_day_splits_per_repo(env):
    env.code.commit("2026-11-15T09:00:00+05:30", "c", {"src/app.py": "x\n" * 3000})
    env.docs.commit("2026-11-15T09:00:00+05:30", "d", {"index.md": "y\n" * 3000})
    env.extra = "[model]\nmax_input_tokens = 4000\n"
    assert env.run("run", "--date", "2026-11-15") == 0
    assert len(env.backend.calls) == 2
    page = env.page("2026-11-15")
    assert page.count("## Details") == 1
    assert page.count("## Worth a look") == 1
    assert page.count("## People") == 1
    assert page.index("### code") < page.index("### docs")


def test_dry_run_makes_no_calls_and_writes_nothing(env, capsys):
    env.code.commit("2026-11-15T09:00:00+05:30", "x", {"src/app.py": "b\n"})
    assert env.run("run", "--date", "2026-11-15", "--dry-run") == 0
    assert env.backend.calls == []
    assert not env.out.exists() or not any(env.out.iterdir())
    out = capsys.readouterr().out
    assert "2026-11-15" in out and "commits=1" in out and "tokens=" in out


def test_save_prompts(env):
    env.code.commit("2026-11-15T09:00:00+05:30", "x", {"src/app.py": "b\n"})
    dest = env.tmp / "prompts"
    env.run("run", "--date", "2026-11-15", "--save-prompts", str(dest))
    names = sorted(p.name for p in dest.iterdir())
    assert names == [
        "2026-11-15-call1-response.txt",
        "2026-11-15-call1-system.md",
        "2026-11-15-call1-user.txt",
    ]


def test_late_commit_warning(env):
    env.run("run")
    env.code.commit("2026-11-14T22:00:00+05:30", "late push", {"src/app.py": "z\n"})
    env.run("run")
    log = env.log_text()
    assert "2026-11-14" in log
    assert "git-summary run --date 2026-11-14 --force" in log


def test_missing_vault_exits_2_before_any_call(env):
    env.vault.rmdir()
    assert env.run("run", "--date", "2026-11-15") == 2


def test_bad_config_exits_2(env, tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text("nope = ")
    assert cli.main(["--config", str(bad), "run"], now=NOW) == 2


def test_concurrent_run_exits_quietly(env):
    env.log.parent.mkdir(parents=True, exist_ok=True)
    with open(env.log.parent / "git-summary.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert env.run("run") == 0
    assert not env.out.exists()
    assert "another run" in env.log_text()


def test_prompt_files_created_beside_config(env):
    env.run("run", "--date", "2026-11-15")
    assert (env.config.parent / "prompt.md").exists()
    assert (env.config.parent / "risk_checklist.md").exists()


def test_path_repo_left_untouched(env):
    local = env.code.clone_to(env.tmp / "local-code")
    git(local, "checkout", "-q", "-b", "wip")
    (local / "scratch.txt").write_text("dirty")
    env.code.commit("2026-11-15T09:00:00+05:30", "x", {"src/app.py": "b\n"})
    env.repo_urls = {}
    env.extra = f'[[repos]]\nname = "code"\npath = "{local}"\n'
    assert env.run("run", "--date", "2026-11-15") == 0
    assert "commits: 1" in env.page("2026-11-15")
    assert git(local, "rev-parse", "--abbrev-ref", "HEAD") == "wip"
    assert (local / "scratch.txt").read_text() == "dirty"
