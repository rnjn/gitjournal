import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PAGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


def day_bounds(d: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time(), tzinfo=tz)
    end = datetime.combine(d + timedelta(days=1), time(), tzinfo=tz)
    return start, end


def in_day(moment: datetime, d: date, tz: ZoneInfo) -> bool:
    start, end = day_bounds(d, tz)
    return start <= moment < end


def page_path(output_dir: Path, d: date) -> Path:
    return output_dir / f"{d.isoformat()}.md"


def existing_pages(output_dir: Path) -> list[date]:
    if not output_dir.is_dir():
        return []
    found = []
    for p in output_dir.iterdir():
        m = PAGE_RE.match(p.name)
        if not m or not p.is_file():
            continue
        try:
            found.append(date.fromisoformat(m.group(1)))
        except ValueError:
            continue
    return sorted(found)


def recent_pages(output_dir: Path, n: int) -> list[date]:
    return existing_pages(output_dir)[-n:]


def _range(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def target_days(
    output_dir: Path,
    tz: ZoneInfo,
    backfill_days: int,
    now: datetime,
    date_from: date | None = None,
    date_to: date | None = None,
    force: bool = False,
) -> list[date]:
    yesterday = now.astimezone(tz).date() - timedelta(days=1)
    existing = set(existing_pages(output_dir))
    if date_from is not None:
        last = min(date_to or date_from, yesterday)
        return [d for d in _range(date_from, last) if force or d not in existing]
    first = min(existing) if existing else yesterday - timedelta(days=backfill_days - 1)
    return [d for d in _range(first, yesterday) if d not in existing]
