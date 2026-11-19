from datetime import datetime
from zoneinfo import ZoneInfo

from gitjournal.citations import Cited, link_citations, not_mentioned_line
from gitjournal.repos import Commit

IST = ZoneInfo("Asia/Kolkata")
CODE = "https://github.com/org/code"
DOCS = "https://github.com/org/docs"


def commit(sha, subject="s"):
    return Commit(sha, sha[:7], "A", datetime(2026, 11, 15, tzinfo=IST), subject, "")


A = commit("a1b2c3d" + "1" * 33, "Add retries")
B = commit("b2c3d4e" + "2" * 33, "Fix typo")
C = commit("c3d4e5f" + "3" * 33, "Docs tweak")
KNOWN = [Cited("code", CODE, A), Cited("code", CODE, B), Cited("docs", DOCS, C)]


def test_links_bare_markers_to_their_repo():
    text, cited, unknown = link_citations("Added retries [a1b2c3d]. Docs [c3d4e5f].", KNOWN)
    assert f"[a1b2c3d]({CODE}/commit/{A.sha})" in text
    assert f"[c3d4e5f]({DOCS}/commit/{C.sha})" in text
    assert cited == {A.sha, C.sha}
    assert unknown == []


def test_longer_prefix_and_grouped_markers():
    text, cited, _ = link_citations("Both [a1b2c3d11, b2c3d4e].", KNOWN)
    assert f"[a1b2c3d11]({CODE}/commit/{A.sha}), [b2c3d4e]({CODE}/commit/{B.sha})" in text
    assert cited == {A.sha, B.sha}


def test_unknown_sha_left_unlinked():
    text, cited, unknown = link_citations("Invented [deadbee] and real [a1b2c3d].", KNOWN)
    assert "[deadbee] and" in text
    assert "deadbee](" not in text
    assert unknown == ["deadbee"]
    assert cited == {A.sha}


def test_existing_links_and_non_sha_brackets_untouched():
    src = f"Already [a1b2c3d]({CODE}/commit/{A.sha}). Checkbox [x] and [TODO]."
    text, cited, unknown = link_citations(src, KNOWN)
    assert text == src
    assert unknown == []


def test_repo_without_web_url_is_cited_but_not_linked():
    known = [Cited("local", None, A)]
    text, cited, unknown = link_citations("See [a1b2c3d].", known)
    assert text == "See `a1b2c3d`."
    assert cited == {A.sha}


def test_not_mentioned_line():
    line = not_mentioned_line(KNOWN, {A.sha})
    assert line == (
        f"Not mentioned above: [b2c3d4e]({CODE}/commit/{B.sha}) Fix typo (code); "
        f"[c3d4e5f]({DOCS}/commit/{C.sha}) Docs tweak (docs)"
    )


def test_not_mentioned_line_empty_when_all_cited():
    assert not_mentioned_line(KNOWN, {A.sha, B.sha, C.sha}) is None
