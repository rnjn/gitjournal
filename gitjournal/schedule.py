import os
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "local.gitjournal"
CRON_MARKER = "# gitjournal"
BASE_PATH = ["/usr/local/bin", "/opt/homebrew/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


class ScheduleError(Exception):
    pass


def _parse_time(value: str) -> tuple[int, int]:
    m = TIME_RE.match(value)
    if not m:
        raise ScheduleError(f"invalid --time {value!r}, expected HH:MM")
    return int(m.group(1)), int(m.group(2))


def _command(config_path: Path, which) -> list[str]:
    exe = which("gitjournal")
    prefix = [exe] if exe else [sys.executable, "-m", "gitjournal.cli"]
    return [*prefix, "--config", str(Path(config_path).expanduser().resolve()), "run"]


def _path_env(which) -> str:
    dirs = []
    for tool in ("git", "claude"):
        found = which(tool)
        if found:
            dirs.append(str(Path(found).parent))
    for d in BASE_PATH:
        if d not in dirs:
            dirs.append(d)
    return ":".join(dict.fromkeys(dirs))


def _plist_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _check_platform(platform: str) -> None:
    if platform != "darwin" and not platform.startswith("linux"):
        raise ScheduleError(f"scheduling is not supported on {platform}")


def install(
    config_path: Path,
    time: str,
    platform: str = sys.platform,
    home: Path | None = None,
    runner=subprocess.run,
    which=shutil.which,
    uid: int | None = None,
) -> str:
    hour, minute = _parse_time(time)
    _check_platform(platform)
    home = home or Path.home()
    cmd = _command(config_path, which)
    path_env = _path_env(which)

    if platform == "darwin":
        uid = os.getuid() if uid is None else uid
        plist_path = _plist_path(home)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        log_dir = home / ".local" / "state" / "gitjournal"
        log_dir.mkdir(parents=True, exist_ok=True)
        plist = {
            "Label": LABEL,
            "ProgramArguments": cmd,
            "StartCalendarInterval": {"Hour": hour, "Minute": minute},
            "EnvironmentVariables": {"PATH": path_env},
            "StandardOutPath": str(log_dir / "launchd.out"),
            "StandardErrorPath": str(log_dir / "launchd.err"),
        }
        runner(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
        plist_path.write_bytes(plistlib.dumps(plist))
        out = runner(
            ["launchctl", "bootstrap", f"gui/{uid}", str(plist_path)],
            capture_output=True,
            text=True,
        )
        if out.returncode != 0:
            raise ScheduleError(f"launchctl bootstrap failed: {out.stderr.strip()}")
        return f"installed launchd agent {plist_path} at {hour:02d}:{minute:02d}"

    line = f"{minute} {hour} * * * PATH={path_env} {shlex.join(cmd)} {CRON_MARKER}"
    _write_crontab(runner, [*_crontab_lines(runner), line])
    return f"installed crontab entry at {hour:02d}:{minute:02d}"


def _crontab_lines(runner) -> list[str]:
    out = runner(["crontab", "-l"], capture_output=True, text=True)
    current = out.stdout if out.returncode == 0 else ""
    return [ln for ln in current.splitlines() if ln.strip() and not ln.endswith(CRON_MARKER)]


def _write_crontab(runner, lines: list[str]) -> None:
    out = runner(["crontab", "-"], input="\n".join(lines) + "\n", capture_output=True, text=True)
    if out.returncode != 0:
        raise ScheduleError(f"crontab update failed: {out.stderr.strip()}")


def remove(
    platform: str = sys.platform,
    home: Path | None = None,
    runner=subprocess.run,
    uid: int | None = None,
) -> str:
    _check_platform(platform)
    home = home or Path.home()
    if platform == "darwin":
        uid = os.getuid() if uid is None else uid
        runner(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
        _plist_path(home).unlink(missing_ok=True)
        return "removed launchd agent"
    _write_crontab(runner, _crontab_lines(runner))
    return "removed crontab entry"
