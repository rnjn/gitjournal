from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from git_summary.render import (
    PageMeta,
    Parsed,
    ResponseError,
    count_risk_flags,
    merge_parsed,
    parse_response,
    read_commit_count,
    render_empty_page,
    render_page,
    title,
    write_atomic,
)

IST = ZoneInfo("Asia/Kolkata")

RESPONSE = """Some preamble the model should not have written.
<narrative>
### code
Did things [a1b2c3d].
</narrative>
<worth_a_look>
- Migration added [a1b2c3d].
  - nested detail
* Default changed [b2c3d4e].
</worth_a_look>
<people>
- **Asha Rao**: src [a1b2c3d]
</people>
"""


def meta(**kw):
    base = dict(
        date=date(2026, 11, 15),
        status="ok",
        repos=["code", "sdk-python"],
        repos_missing=[],
        commits=2,
        authors=["Asha Rao", "dependabot[bot]"],
        risk_flags=2,
        model="claude-sonnet-5-5",
        generated_at=datetime(2026, 11, 16, 8, 0, 12, tzinfo=IST),
    )
    return PageMeta(**{**base, **kw})


def test_parse_response():
    p = parse_response(RESPONSE)
    assert p.narrative == "### code\nDid things [a1b2c3d]."
    assert p.worth_a_look.startswith("- Migration added")
    assert p.people == "- **Asha Rao**: src [a1b2c3d]"


@pytest.mark.parametrize("missing", ["narrative", "worth_a_look", "people"])
def test_parse_response_missing_tag(missing):
    text = RESPONSE.replace(f"<{missing}>", "").replace(f"</{missing}>", "")
    with pytest.raises(ResponseError, match=missing):
        parse_response(text)


def test_count_risk_flags():
    assert count_risk_flags(parse_response(RESPONSE).worth_a_look) == 2
    assert count_risk_flags("Nothing flagged.") == 0


def test_merge_parsed_concatenates_and_drops_nothing_flagged():
    a = Parsed("### code\nA", "- risk A", "- Asha: code")
    b = Parsed("### docs\nB", "Nothing flagged.", "- Vikram: docs")
    m = merge_parsed([a, b])
    assert m.narrative == "### code\nA\n\n### docs\nB"
    assert m.worth_a_look == "- risk A"
    assert m.people == "- Asha: code\n- Vikram: docs"


def test_merge_parsed_all_nothing_flagged():
    a = Parsed("A", "Nothing flagged.", "p")
    assert merge_parsed([a, a]).worth_a_look == "Nothing flagged."


def test_title():
    assert title(date(2026, 11, 15)) == "# Git summary: Sunday 15 November 2026"
    assert title(date(2026, 11, 2)) == "# Git summary: Monday 2 November 2026"


def test_render_page_ok():
    page = render_page(
        meta(),
        Parsed("### code\nN", "- R", "- P"),
        missing={},
        reduced=[],
        not_mentioned="Not mentioned above: x",
    )
    assert page.startswith(
        "---\n"
        "date: 2026-11-15\n"
        "status: ok\n"
        "repos: [code, sdk-python]\n"
        "repos_missing: []\n"
        "commits: 2\n"
        'authors: ["Asha Rao", "dependabot[bot]"]\n'
        "risk_flags: 2\n"
        "model: claude-sonnet-5-5\n"
        "generated_at: 2026-11-16T08:00:12+05:30\n"
        "tags: [git-summary]\n"
        "---\n\n"
        "# Git summary: Sunday 15 November 2026\n"
    )
    assert page.index("## Worth a look") < page.index("## Details") < page.index("## People")
    assert page.rstrip().endswith("Not mentioned above: x")
    assert "[!warning]" not in page


def test_render_page_partial_callout_and_reduced_note():
    page = render_page(
        meta(status="partial", repos_missing=["infra"]),
        Parsed("N", "Nothing flagged.", "P"),
        missing={"infra": "git fetch timed out after 120s"},
        reduced=["code: src/big.py (a1b2c3d)"],
        not_mentioned=None,
    )
    assert "repos_missing: [infra]" in page
    callout = page[page.index("> [!warning]") : page.index("## Worth a look")]
    assert "infra" in callout
    assert "git fetch timed out after 120s" in callout
    assert "git-summary run --date 2026-11-15 --force" in callout
    assert "src/big.py (a1b2c3d)" in page
    assert page.index("[!warning]") < page.index("## Worth a look")


def test_render_empty_page():
    page = render_empty_page(meta(status="empty", commits=0, authors=[], risk_flags=0), {})
    assert "status: empty" in page
    assert "authors: []" in page
    assert page.rstrip().endswith("No commits on main in any repository.")
    assert "## Details" not in page


def test_write_atomic_and_read_commit_count(tmp_path):
    target = tmp_path / "vault" / "Git Summary" / "2026-11-15.md"
    write_atomic(target, render_empty_page(meta(commits=7), {}))
    assert target.exists()
    assert list(target.parent.iterdir()) == [target]
    assert read_commit_count(target) == 7


def test_read_commit_count_missing(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("no frontmatter")
    assert read_commit_count(p) is None
