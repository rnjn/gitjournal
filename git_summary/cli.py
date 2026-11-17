import argparse
import fcntl
import os
import sys
from datetime import date, datetime
from pathlib import Path

from git_summary.backends import make_backend
from git_summary.config import DEFAULT_CONFIG_PATH, ConfigError, ensure_prompt_files, load_config
from git_summary.days import target_days
from git_summary.log import setup_logging
from git_summary.pipeline import Pipeline
from git_summary.vault import VaultError, publish

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
COMPLETE = {"ok", "empty", "dry-run"}


class UsageError(Exception):
    pass


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=argparse.SUPPRESS)

    parser = argparse.ArgumentParser(prog="git-summary", parents=[common])
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", parents=[common], help="generate missing daily pages")
    run.add_argument("--date", type=date.fromisoformat)
    run.add_argument("--from", dest="date_from", type=date.fromisoformat)
    run.add_argument("--to", dest="date_to", type=date.fromisoformat)
    run.add_argument("--force", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--backend", choices=["api", "claude_code"])
    run.add_argument("--save-prompts", type=Path)

    schedule = sub.add_parser("schedule", parents=[common], help="manage the daily job")
    actions = schedule.add_subparsers(dest="action", required=True)
    install = actions.add_parser("install", parents=[common])
    install.add_argument("--time", default="08:00")
    actions.add_parser("remove", parents=[common])
    return parser


def _range(args) -> tuple[date | None, date | None]:
    if args.date and (args.date_from or args.date_to):
        raise UsageError("--date cannot be combined with --from/--to")
    if args.date_to and not args.date_from:
        raise UsageError("--to requires --from")
    if args.force and not (args.date or args.date_from):
        raise UsageError("--force requires --date or --from/--to")
    if args.date:
        return args.date, args.date
    if args.date_from:
        to = args.date_to or date.max
        if to < args.date_from:
            raise UsageError("--to is before --from")
        return args.date_from, to
    return None, None


def _check_vault(vault: Path) -> None:
    if not vault.is_dir() or not os.access(vault, os.W_OK):
        raise UsageError(f"vault path missing or not writable: {vault}")


def run(args, cfg, now, backend_factory) -> int:
    log = setup_logging(cfg.log_file)
    try:
        date_from, date_to = _range(args)
        _check_vault(cfg.vault_path)
    except UsageError as e:
        log.error("%s", e)
        return EXIT_USAGE
    ensure_prompt_files(cfg.config_dir)

    lock_path = cfg.log_file.parent / "git-summary.lock"
    with open(lock_path, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("another run holds %s; exiting", lock_path)
            return EXIT_OK
        return _run_locked(args, cfg, now, backend_factory, log, date_from, date_to)


def _run_locked(args, cfg, now, backend_factory, log, date_from, date_to) -> int:
    now = now or datetime.now(cfg.tz)
    targets = target_days(
        cfg.output_dir,
        cfg.tz,
        cfg.first_run_backfill_days,
        now,
        date_from,
        date_to,
        args.force,
    )
    log.info("run start: %d day(s) to generate, dry_run=%s", len(targets), args.dry_run)
    try:
        backend = backend_factory(cfg.model, args.backend)
    except Exception as e:
        log.error("cannot create backend: %s", e)
        return EXIT_USAGE

    pipeline = Pipeline(cfg, backend, log, now, args.dry_run, args.save_prompts)
    pipeline.fetch_all()
    pipeline.check_late_commits(set(targets))

    outcomes = []
    for d in targets:
        try:
            result = pipeline.generate(d)
        except Exception as e:
            log.exception("%s failed unexpectedly", d)
            outcomes.append("failed")
            print(f"{d} failed: {e}")
            continue
        outcomes.append(result.outcome)
        line = (
            f"{d} commits={result.commits} tokens={result.tokens} "
            f"calls={result.calls} outcome={result.outcome}"
        )
        if result.error:
            line += f" error={result.error}"
            log.error("%s", line)
        else:
            log.info("%s", line)
        if args.dry_run:
            print(line)

    code = EXIT_OK if all(o in COMPLETE for o in outcomes) else EXIT_FAILED
    if cfg.vault_git_push and not args.dry_run:
        try:
            message = publish(cfg.vault_path, cfg.output_folder)
            log.info("pushed vault: %s", message or "no new pages")
        except VaultError as e:
            log.error("vault push failed: %s", e)
            code = EXIT_FAILED
    log.info("run end: exit=%d", code)
    return code


def main(argv: list[str] | None = None, now: datetime | None = None, backend_factory=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    config_path = getattr(args, "config", DEFAULT_CONFIG_PATH)
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        print(f"git-summary: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.command == "run":
        return run(args, cfg, now, backend_factory or make_backend)

    from git_summary import schedule

    try:
        if args.action == "install":
            print(schedule.install(config_path, args.time))
        else:
            print(schedule.remove())
    except schedule.ScheduleError as e:
        print(f"git-summary: {e}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
