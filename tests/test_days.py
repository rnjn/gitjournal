from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from gitjournal.days import day_bounds, existing_pages, in_day, recent_pages, target_days

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 16, 8, 0, tzinfo=IST)


def touch(d, *names):
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_text("x")


def test_day_bounds_are_ist_midnights():
    start, end = day_bounds(date(2026, 11, 15), IST)
    assert start == datetime(2026, 11, 15, tzinfo=IST)
    assert end == datetime(2026, 11, 16, tzinfo=IST)
    assert start.utcoffset() == timedelta(hours=5, minutes=30)


def test_in_day_boundaries_independent_of_input_zone():
    d = date(2026, 11, 15)
    utc = ZoneInfo("UTC")
    ny = ZoneInfo("America/New_York")
    assert in_day(datetime(2026, 11, 15, 0, 0, 0, tzinfo=IST), d, IST)
    assert in_day(datetime(2026, 11, 15, 23, 59, 59, tzinfo=IST), d, IST)
    assert not in_day(datetime(2026, 11, 16, 0, 0, 0, tzinfo=IST), d, IST)
    assert not in_day(datetime(2026, 11, 14, 23, 59, 59, tzinfo=IST), d, IST)
    assert in_day(datetime(2026, 11, 15, 18, 29, 59, tzinfo=utc), d, IST)
    assert not in_day(datetime(2026, 11, 15, 18, 30, 0, tzinfo=utc), d, IST)
    assert in_day(datetime(2026, 11, 15, 13, 29, 59, tzinfo=ny), d, IST)


def test_existing_pages_ignores_other_files(tmp_path):
    touch(
        tmp_path, "2026-11-10.md", "2026-11-02.md", "notes.md", "2026-11-03.md.tmp", "2026-13-01.md"
    )
    assert existing_pages(tmp_path) == [date(2026, 11, 2), date(2026, 11, 10)]


def test_existing_pages_missing_dir(tmp_path):
    assert existing_pages(tmp_path / "nope") == []


def test_first_run_backfills_n_days_ending_yesterday(tmp_path):
    days = target_days(tmp_path, IST, 30, NOW)
    assert len(days) == 30
    assert days[0] == date(2026, 10, 17)
    assert days[-1] == date(2026, 11, 15)


def test_yesterday_is_ist_not_machine_local(tmp_path):
    late_utc = datetime(2026, 11, 15, 20, 0, tzinfo=ZoneInfo("UTC"))
    days = target_days(tmp_path, IST, 1, late_utc)
    assert days == [date(2026, 11, 15)]


def test_normal_run_fills_gaps_from_earliest_page(tmp_path):
    touch(tmp_path, "2026-11-10.md", "2026-11-12.md", "2026-11-15.md")
    assert target_days(tmp_path, IST, 30, NOW) == [
        date(2026, 11, 11),
        date(2026, 11, 13),
        date(2026, 11, 14),
    ]


def test_nothing_to_do(tmp_path):
    touch(tmp_path, "2026-11-14.md", "2026-11-15.md")
    assert target_days(tmp_path, IST, 30, NOW) == []


def test_explicit_range_skips_existing(tmp_path):
    touch(tmp_path, "2026-11-02.md")
    days = target_days(tmp_path, IST, 30, NOW, date(2026, 11, 1), date(2026, 11, 3))
    assert days == [date(2026, 11, 1), date(2026, 11, 3)]


def test_explicit_range_force_includes_existing(tmp_path):
    touch(tmp_path, "2026-11-02.md")
    days = target_days(tmp_path, IST, 30, NOW, date(2026, 11, 1), date(2026, 11, 3), force=True)
    assert days == [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]


def test_explicit_range_never_includes_today(tmp_path):
    days = target_days(tmp_path, IST, 30, NOW, date(2026, 11, 15), date(2026, 11, 20))
    assert days == [date(2026, 11, 15)]


def test_recent_pages(tmp_path):
    touch(tmp_path, "2026-11-01.md", "2026-11-05.md", "2026-11-09.md", "2026-11-10.md")
    assert recent_pages(tmp_path, 3) == [date(2026, 11, 5), date(2026, 11, 9), date(2026, 11, 10)]
