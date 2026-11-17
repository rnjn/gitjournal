import plistlib
import subprocess
from pathlib import Path

import pytest

from git_summary.schedule import LABEL, ScheduleError, install, remove

CONFIG = Path("/cfg/config.toml")


def which(name):
    return {
        "git": "/opt/git/bin/git",
        "claude": "/opt/claude/bin/claude",
        "git-summary": "/home/me/.local/bin/git-summary",
    }.get(name)


class Runner:
    def __init__(self, crontab=""):
        self.calls = []
        self.crontab = crontab

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[:2] == ["crontab", "-l"]:
            return subprocess.CompletedProcess(cmd, 0 if self.crontab else 1, self.crontab, "")
        if cmd[:2] == ["crontab", "-"]:
            self.crontab = kwargs["input"]
        return subprocess.CompletedProcess(cmd, 0, "", "")


def test_launchd_install_writes_plist_and_bootstraps(tmp_path):
    runner = Runner()
    install(CONFIG, "07:45", platform="darwin", home=tmp_path, runner=runner, which=which, uid=501)
    plist_path = tmp_path / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == [
        "/home/me/.local/bin/git-summary",
        "--config",
        "/cfg/config.toml",
        "run",
    ]
    assert plist["StartCalendarInterval"] == {"Hour": 7, "Minute": 45}
    path = plist["EnvironmentVariables"]["PATH"].split(":")
    assert path[:2] == ["/opt/git/bin", "/opt/claude/bin"]
    assert "/usr/bin" in path
    assert ["launchctl", "bootstrap", "gui/501", str(plist_path)] in runner.calls


def test_launchd_remove(tmp_path):
    runner = Runner()
    install(CONFIG, "08:00", platform="darwin", home=tmp_path, runner=runner, which=which, uid=501)
    remove(platform="darwin", home=tmp_path, runner=runner, uid=501)
    assert not (tmp_path / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()
    assert ["launchctl", "bootout", f"gui/501/{LABEL}"] in runner.calls


def test_cron_install_replaces_previous_entry_and_keeps_others(tmp_path):
    runner = Runner("0 1 * * * backup.sh\n5 5 * * * old # git-summary\n")
    install(CONFIG, "08:00", platform="linux", home=tmp_path, runner=runner, which=which)
    lines = runner.crontab.strip().splitlines()
    assert lines[0] == "0 1 * * * backup.sh"
    assert len(lines) == 2
    assert lines[1].startswith("0 8 * * * PATH=/opt/git/bin:/opt/claude/bin:")
    assert lines[1].endswith(
        "/home/me/.local/bin/git-summary --config /cfg/config.toml run # git-summary"
    )


def test_cron_remove(tmp_path):
    runner = Runner("0 1 * * * backup.sh\n0 8 * * * x # git-summary\n")
    remove(platform="linux", home=tmp_path, runner=runner)
    assert runner.crontab == "0 1 * * * backup.sh\n"


@pytest.mark.parametrize("bad", ["8", "25:00", "08:60", "ab:cd"])
def test_bad_time(tmp_path, bad):
    with pytest.raises(ScheduleError):
        install(CONFIG, bad, platform="linux", home=tmp_path, runner=Runner(), which=which)


def test_unsupported_platform(tmp_path):
    with pytest.raises(ScheduleError):
        install(CONFIG, "08:00", platform="win32", home=tmp_path, runner=Runner(), which=which)
