from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from git_summary.config import RepoConfig
from git_summary.repos import (
    RepoError,
    commit_files,
    commits_for_day,
    derive_web_url,
    detect_branch,
    prepare,
)
from tests.gitutil import Repo, git

IST = ZoneInfo("Asia/Kolkata")
D = date(2026, 11, 15)


@pytest.fixture
def remote(tmp_path):
    r = Repo(tmp_path / "remote")
    r.commit("2026-11-14T23:59:59+05:30", "before")
    r.commit("2026-11-15T00:00:00+05:30", "first of day", author="Vikram N")
    r.commit("2026-11-15T23:59:59+05:30", "last of day\n\nbody line one\nbody line two")
    r.commit("2026-11-16T00:00:00+05:30", "next day")
    return r


def url_repo(remote, tmp_path):
    cfg = RepoConfig(name="code", url=str(remote.path))
    return prepare(cfg, tmp_path / "cache")


def test_url_repo_bare_clone_exposes_origin_refs(remote, tmp_path):
    gitdir = url_repo(remote, tmp_path)
    assert gitdir == tmp_path / "cache" / "code.git"
    assert git(gitdir, "rev-parse", "--is-bare-repository") == "true"
    assert detect_branch(gitdir, None) == "main"
    assert git(gitdir, "rev-parse", "origin/main") == git(remote.path, "rev-parse", "HEAD")


def test_url_repo_refetch_picks_up_new_commits(remote, tmp_path):
    url_repo(remote, tmp_path)
    new = remote.commit("2026-11-15T12:00:00+05:30", "late")
    gitdir = url_repo(remote, tmp_path)
    assert git(gitdir, "rev-parse", "origin/main") == new


def test_commit_selection_uses_exclusive_ist_midnight(remote, tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    gitdir = url_repo(remote, tmp_path)
    commits = commits_for_day(gitdir, "main", D, IST)
    assert [c.subject for c in commits] == ["first of day", "last of day"]
    first, last = commits
    assert first.author == "Vikram N"
    assert first.committed == datetime(2026, 11, 15, 0, 0, 0, tzinfo=IST)
    assert len(first.short) >= 7 and first.sha.startswith(first.short)
    assert last.body == "body line one\nbody line two"


def test_commit_selection_survives_out_of_order_dates(tmp_path):
    r = Repo(tmp_path / "remote")
    r.commit("2026-11-15T10:00:00+05:30", "in day")
    r.commit("2026-11-13T10:00:00+05:30", "older date on top")
    r.commit("2026-11-15T11:00:00+05:30", "in day again")
    gitdir = url_repo(r, tmp_path)
    assert [c.subject for c in commits_for_day(gitdir, "main", D, IST)] == [
        "in day",
        "in day again",
    ]


def test_path_repo_fetch_leaves_working_tree_alone(remote, tmp_path):
    local = remote.clone_to(tmp_path / "local")
    git(local, "checkout", "-q", "-b", "feature")
    (local / "dirty.txt").write_text("uncommitted")
    head_before = git(local, "rev-parse", "HEAD")
    new = remote.commit("2026-11-15T12:00:00+05:30", "pushed later")

    gitdir = prepare(RepoConfig(name="infra", path=local), tmp_path / "cache")

    assert gitdir == local
    assert git(local, "rev-parse", "origin/main") == new
    assert git(local, "rev-parse", "--abbrev-ref", "HEAD") == "feature"
    assert git(local, "rev-parse", "HEAD") == head_before
    assert (local / "dirty.txt").read_text() == "uncommitted"
    assert "dirty.txt" in git(local, "status", "--porcelain")


def test_branch_detection_fallbacks(tmp_path):
    r = Repo(tmp_path / "remote", branch="master")
    r.commit("2026-11-15T10:00:00+05:30")
    local = r.clone_to(tmp_path / "local")
    git(local, "remote", "set-head", "origin", "--delete")
    assert detect_branch(local, None) == "master"
    assert detect_branch(local, "trunk") == "trunk"


def test_branch_detection_from_origin_head(tmp_path):
    r = Repo(tmp_path / "remote", branch="develop")
    r.commit("2026-11-15T10:00:00+05:30")
    local = r.clone_to(tmp_path / "local")
    assert detect_branch(local, None) == "develop"


def test_missing_remote_raises(tmp_path):
    with pytest.raises(RepoError):
        prepare(RepoConfig(name="gone", url=str(tmp_path / "nope")), tmp_path / "cache")


def test_missing_path_raises(tmp_path):
    with pytest.raises(RepoError):
        prepare(RepoConfig(name="gone", path=tmp_path / "nope"), tmp_path / "cache")


@pytest.mark.parametrize(
    "remote_url, expected",
    [
        ("git@github.com:org/code.git", "https://github.com/org/code"),
        ("git@github.com:org/code", "https://github.com/org/code"),
        ("ssh://git@github.com/org/code.git", "https://github.com/org/code"),
        ("https://github.com/org/code.git", "https://github.com/org/code"),
        ("https://user:tok@github.com/org/code.git", "https://github.com/org/code"),
        ("/local/path", None),
    ],
)
def test_derive_web_url(remote_url, expected):
    assert derive_web_url(remote_url) == expected


def test_commit_files_numstat_and_patches(tmp_path):
    r = Repo(tmp_path / "remote")
    r.commit("2026-11-14T10:00:00+05:30", "base", {"src/a.py": "a\n", "old name.txt": "x\n" * 5})
    sha = r.commit(
        "2026-11-15T10:00:00+05:30",
        "mixed",
        {
            "src/a.py": "a\nb\n",
            "README.md": "hi\n",
            "img/logo.png": b"\x89PNG\x00\x01\x02",
            "old name.txt": None,
            "new name.txt": "x\n" * 5,
        },
    )
    gitdir = url_repo(r, tmp_path)
    files = {f.path: f for f in commit_files(gitdir, sha)}

    assert set(files) == {"src/a.py", "README.md", "img/logo.png", "new name.txt"}
    assert (files["src/a.py"].added, files["src/a.py"].deleted) == (1, 0)
    assert "+b" in files["src/a.py"].patch
    assert files["img/logo.png"].binary
    assert "Binary files" in files["img/logo.png"].patch
    assert files["new name.txt"].old_path == "old name.txt"
    assert "rename from old name.txt" in files["new name.txt"].patch


def test_merge_commit_patch_against_first_parent(tmp_path):
    r = Repo(tmp_path / "remote")
    r.commit("2026-11-14T10:00:00+05:30", "base", {"a.txt": "a\n"})
    git(r.path, "checkout", "-q", "-b", "side")
    r.commit("2026-11-15T09:00:00+05:30", "side work", {"b.txt": "b\n"})
    git(r.path, "checkout", "-q", "main")
    r.commit("2026-11-15T09:30:00+05:30", "main work", {"c.txt": "c\n"})
    env = {
        "GIT_AUTHOR_DATE": "2026-11-15T10:00:00+05:30",
        "GIT_COMMITTER_DATE": "2026-11-15T10:00:00+05:30",
    }
    git(r.path, "merge", "-q", "--no-ff", "side", "-m", "merge side", env=env)

    gitdir = url_repo(r, tmp_path)
    commits = commits_for_day(gitdir, "main", D, IST)
    assert [c.subject for c in commits] == ["main work", "merge side"]
    assert [f.path for f in commit_files(gitdir, commits[1].sha)] == ["b.txt"]
