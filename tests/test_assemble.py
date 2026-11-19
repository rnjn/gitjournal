from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from gitjournal.assemble import (
    CommitData,
    RepoDay,
    area_of,
    build_user_message,
    commit_areas,
    is_omitted,
    render_commit,
)
from gitjournal.config import DEFAULT_OMIT_PATCH
from gitjournal.repos import Commit, FileChange

IST = ZoneInfo("Asia/Kolkata")


def fc(path, added=1, deleted=0, patch=None, old_path=None, binary=False):
    return FileChange(path, old_path, added, deleted, binary, patch or f"diff --git a/{path}\n+x\n")


def cd(short="a1b2c3d", subject="Fix thing", body="", files=(), author="Asha Rao", hour=10):
    commit = Commit(
        sha=short + "0" * (40 - len(short)),
        short=short,
        author=author,
        committed=datetime(2026, 11, 15, hour, 5, tzinfo=IST),
        subject=subject,
        body=body,
    )
    return CommitData(commit, list(files))


@pytest.mark.parametrize(
    "path, area",
    [("src/a/b.py", "src"), ("README.md", "(root)"), (".github/workflows/ci.yml", ".github")],
)
def test_area_of(path, area):
    assert area_of(path) == area


def test_commit_areas_include_rename_source():
    c = cd(files=[fc("b/x.py", old_path="a/x.py"), fc("README.md"), fc("b/y.py")])
    assert commit_areas(c) == ["(root)", "a", "b"]


@pytest.mark.parametrize(
    "path, omitted",
    [
        ("package-lock.json", True),
        ("web/package-lock.json", True),
        ("vendor/github.com/x/y.go", True),
        ("svc/vendor/x.go", True),
        ("app.min.js", True),
        ("src/__snapshots__/a.txt", True),
        ("api/v1/x.pb.go", True),
        ("src/app.py", False),
        ("vendored/x.go", False),
    ],
)
def test_is_omitted(path, omitted):
    assert is_omitted(path, DEFAULT_OMIT_PATCH) is omitted


def test_render_commit_full():
    c = cd(
        body="Longer body.\nSecond line.",
        files=[
            fc("src/app.py", 3, 1, patch="diff --git a/src/app.py b/src/app.py\n+new\n"),
            fc("package-lock.json", 812, 640, patch="diff --git huge\n"),
            fc("logo.png", binary=True, patch="diff --git a/logo.png\nBinary files differ\n"),
            fc("new/x.py", 0, 0, old_path="old/x.py", patch="diff --git rename\n"),
        ],
    )
    text = render_commit(c, DEFAULT_OMIT_PATCH)
    assert text.startswith('<commit sha="a1b2c3d" author="Asha Rao" time="2026-11-15 10:05 IST">')
    assert text.rstrip().endswith("</commit>")
    assert "Fix thing\n\nLonger body.\nSecond line." in text
    assert "<areas>(root), new, old, src</areas>" in text
    assert "3\t1\tsrc/app.py" in text
    assert "812\t640\tpackage-lock.json" in text
    assert "-\t-\tlogo.png" in text
    assert "0\t0\told/x.py => new/x.py" in text
    assert "+new" in text
    assert "[patch omitted: package-lock.json, +812 -640]" in text
    assert "diff --git huge" not in text
    assert "Binary files differ" in text


def test_render_commit_reduced_files():
    c = cd(files=[fc("src/big.py", 5000, 10, patch="diff --git big\n")])
    text = render_commit(c, [], reduced={(c.commit.sha, "src/big.py")})
    assert "diff --git big" not in text
    assert "[patch reduced to fit context: src/big.py, +5000 -10]" in text
    assert "5000\t10\tsrc/big.py" in text


def test_author_attribute_is_escaped():
    text = render_commit(cd(author='Bob "the" <bot>'), [])
    assert 'author="Bob &quot;the&quot; &lt;bot&gt;"' in text


def test_build_user_message_layout():
    code = RepoDay(
        "code",
        "https://github.com/org/code",
        [
            cd("aaaaaaa", files=[fc("src/a.py"), fc("docs/x.md")], hour=9),
            cd("bbbbbbb", files=[fc("src/b.py")], hour=11),
        ],
    )
    docs = RepoDay("docs", "https://github.com/org/docs", [])
    web = RepoDay("website", None, [])
    msg = build_user_message(date(2026, 11, 15), [code, docs, web], [])

    assert msg.startswith("Date: 2026-11-15 (Sunday)")
    assert '<repo name="code" web_url="https://github.com/org/code" commits="2">' in msg
    assert "<area_counts>src: 2, docs: 1</area_counts>" in msg
    assert msg.index("aaaaaaa") < msg.index("bbbbbbb")
    assert "</repo>" in msg
    assert "Repositories with no commits on this day: docs, website" in msg
    assert '<repo name="docs"' not in msg


def test_build_user_message_all_repos_active_has_no_empty_line():
    code = RepoDay("code", None, [cd()])
    msg = build_user_message(date(2026, 11, 15), [code], [])
    assert "no commits" not in msg
