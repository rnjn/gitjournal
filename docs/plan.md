# Build plan

Each step is written test first: write the tests, see them fail, implement, run `make test` and `make lint`, then commit.

| # | Step | Files | Tests to run |
| --- | --- | --- | --- |
| 0 | Scaffold: uv project, ruff, pytest, Makefile, git | `pyproject.toml`, `Makefile`, `.gitignore`, `git_summary/__init__.py`, `tests/conftest.py` | `make test` (smoke), `make lint` |
| 1 | Config load and validation | `git_summary/config.py` | `tests/test_config.py` |
| 2 | IST day boundaries, which days to generate | `git_summary/days.py` | `tests/test_days.py` |
| 3 | Git: bare clone + refspec, fetch, branch detection, web URL, commit selection with Python boundary filter, show/numstat | `git_summary/repos.py`, `tests/gitutil.py` | `tests/test_repos.py` |
| 4 | Per-commit blocks, areas, omit_patch filter, prompt layout | `git_summary/assemble.py` | `tests/test_assemble.py` |
| 5 | SHA markers to links, unknown and uncited checks | `git_summary/citations.py` | `tests/test_citations.py` |
| 6 | Parse tagged response, frontmatter, page body, partial callout, atomic write | `git_summary/render.py` | `tests/test_render.py` |
| 7 | Token budget, per-repo split, last-resort reduction | `git_summary/budget.py` | `tests/test_budget.py` |
| 8 | Backends behind `summarise(system, user)`, retries, API key lookup | `git_summary/backends/{__init__,api,claude_code,fake}.py` | `tests/test_backends.py` |
| 9 | Default prompt files, copied beside config on first run | `git_summary/defaults/prompt.md`, `git_summary/defaults/risk_checklist.md` | `tests/test_config.py` |
| 10 | CLI: run loop, flags, lock, exit codes, log rotation, late-commit check, `--save-prompts`, `--dry-run` | `git_summary/cli.py`, `git_summary/log.py` | `tests/test_cli.py` (acceptance criteria) |
| 11 | launchd and cron install/remove | `git_summary/schedule.py` | `tests/test_schedule.py` |
| 12 | Acceptance sweep against the spec checklist; confirm Sonnet context limit and Claude Code print-mode flags | all | `make test`, `make lint` |
