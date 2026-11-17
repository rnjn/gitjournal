from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from git_summary.assemble import CommitData, RepoDay
from git_summary.budget import (
    OUTPUT_RESERVE,
    BudgetError,
    char_estimate,
    input_budget,
    plan_calls,
)
from git_summary.repos import Commit, FileChange

IST = ZoneInfo("Asia/Kolkata")
D = date(2026, 11, 15)


def chars(system: str, user: str) -> int:
    return len(system) + len(user)


def commit(short, *files):
    c = Commit(short + "0" * 33, short, "A", datetime(2026, 11, 15, 10, tzinfo=IST), "s", "")
    return CommitData(
        c, [FileChange(p, None, 1, 0, False, f"diff --git {p}\n" + "x" * n) for p, n in files]
    )


def repos():
    return [
        RepoDay("code", None, [commit("aaaaaaa", ("src/a.py", 2000), ("src/b.py", 500))]),
        RepoDay("docs", None, [commit("bbbbbbb", ("guide.md", 1500))]),
        RepoDay("website", None, []),
    ]


def test_input_budget():
    assert input_budget(200_000, 0) == 200_000 - OUTPUT_RESERVE
    assert input_budget(200_000, 50_000) == 50_000


def test_char_estimate():
    assert char_estimate("abc", "abcdef") == 4


def test_fits_in_one_call():
    calls = plan_calls(D, repos(), [], "sys", chars, 100_000)
    assert len(calls) == 1
    assert "aaaaaaa" in calls[0].user and "bbbbbbb" in calls[0].user
    assert "no commits on this day: website" in calls[0].user
    assert calls[0].reduced == []


def test_splits_per_repo_in_config_order_when_day_does_not_fit():
    calls = plan_calls(D, repos(), [], "sys", chars, 3200)
    assert len(calls) == 2
    assert "aaaaaaa" in calls[0].user and "bbbbbbb" not in calls[0].user
    assert "bbbbbbb" in calls[1].user and "aaaaaaa" not in calls[1].user
    assert "website" not in calls[0].user
    assert "no commits on this day: website" in calls[1].user
    assert all(c.reduced == [] for c in calls)


def test_reduces_largest_patches_first_until_repo_fits():
    calls = plan_calls(D, repos(), [], "sys", chars, 2400)
    code = calls[0]
    assert code.reduced == ["code: src/a.py (aaaaaaa)"]
    assert "[patch reduced to fit context: src/a.py, +1 -0]" in code.user
    assert "x" * 500 in code.user
    assert chars("sys", code.user) <= 2400


def test_fails_when_nothing_left_to_reduce():
    with pytest.raises(BudgetError, match="code"):
        plan_calls(D, repos(), [], "sys", chars, 300)


def test_char_estimate_is_conservative_for_dense_code():
    measured_chars_per_token = 2.2
    chars = 2_200_000
    assert char_estimate("", "x" * chars) >= chars / measured_chars_per_token
