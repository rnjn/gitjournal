# git-summary

A daily engineering log, written for you from your git history.

Every morning `git-summary` looks at what landed on the main branch of each repository you care about, reads the actual patches (not just the commit messages), and has Claude write one Markdown page for the day. Pages go into a folder of your choice, typically an Obsidian vault, and can be committed and pushed to a git repository of their own.

It is built for someone who owns or oversees several repositories and wants to know, in a few minutes each morning, what changed and what deserves a closer look.

## What a page looks like

```markdown
# Git summary: Monday 16 November 2026

## Worth a look

- Dropped the `legacy_tokens` column in a migration labelled "Tidy tests"; the message does not mention it. Priya S. [a1b2c3d]

## Details

### api

**auth**
- Added retry with exponential backoff to the token refresh client, capped at three attempts. [e4f5a6b]
- Moved session expiry from 24h to 12h and updated the related tests.
  - [9c8d7e6, 1f2e3d4]

### infra

**k8s**
- Raised shard volumes from 20Gi to 40Gi. [5a6b7c8]

## People

- **Priya S.**: auth and migrations in api. [a1b2c3d, e4f5a6b]
- **dependabot[bot]**: dependency bumps in web. [0d9e8f7]
```

Every SHA links to the commit on GitHub. Commits the summary did not mention are listed at the end of the page, so nothing is silently dropped. Each page also has YAML frontmatter (`date`, `status`, `repos`, `commits`, `authors`, `risk_flags`, `model`, and more) for querying with Obsidian Dataview or anything else.

## Features

- **Reads patches, not just messages.** It flags commits whose message does not match what the patch does.
- **"Worth a look" section** driven by an editable checklist: migrations, auth and permission changes, deleted tests, infra and IAM changes, config and retention changes, and so on.
- **Day boundaries in your timezone.** Each page covers midnight to midnight local time, using commit times rather than push times.
- **Catches up by itself.** Each run writes every missing day up to yesterday; on first run it backfills a configurable number of days.
- **Large days still fit.** If a day is too big for one model call, it is split per repository, and the largest patches are trimmed as a last resort, which the page notes.
- **Noise filtered.** Lock files, minified and generated files, snapshots and vendored code are summarised by line count only. The patterns are configurable.
- **Partial days are visible.** If a repository cannot be fetched, the page says so at the top and gives the exact command to regenerate it.
- **Optional git push of the output folder** after each run.
- **Scheduled with launchd (macOS) or cron (Linux)** by one command.

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/) (or pipx)
- git 2.37+
- One of:
  - Claude Code, logged in (the `claude_code` backend uses your existing Claude Code login), or
  - an Anthropic API key (the `api` backend)

## Install

```bash
git clone <this repo> && cd git-summary
uv tool install .            # puts `git-summary` on your PATH
```

Or run it in place without installing: `uv run --project /path/to/git-summary git-summary ...`.

## Configure

Create `~/.config/git-summary/config.toml`:

```toml
timezone = "Asia/Kolkata"               # day boundaries
vault_path = "/path/to/vault"           # must exist
output_folder = "Git Summary"           # pages go in vault_path/output_folder
first_run_backfill_days = 30
vault_git_push = false                  # commit and push the output folder after each run

[model]
backend = "claude_code"                 # or "api"
name = "claude-sonnet-5-5"
max_input_tokens = 0                    # 0 = use the model's context limit

# Each repo needs a name and exactly one of `url` or `path`.
[[repos]]
name = "api"
url = "git@github.com:acme/api.git"     # kept as a bare clone in the cache

[[repos]]
name = "infra"
path = "/Users/me/src/infra"            # existing clone: fetched only, working tree untouched
branch = "main"                         # optional; default is detected from origin/HEAD
web_url = "https://github.com/acme/infra"   # optional; default is derived from the remote

[filters]
omit_patch = ["**/package-lock.json", "**/dist/**", "**/*.generated.*"]
```

Other optional keys: `cache_dir` (default `~/.cache/git-summary/repos`) and `log_file` (default `~/.local/state/git-summary/git-summary.log`).

On first run, `prompt.md` and `risk_checklist.md` are copied next to the config. Edit them to change the writing style or what gets flagged; your edits are never overwritten.

### API key

The `api` backend reads `ANTHROPIC_API_KEY`. Scheduled jobs do not see your shell environment, so on macOS it falls back to the login Keychain:

```bash
security add-generic-password -s git-summary -a anthropic -w
```

### Pushing the output folder

Set `vault_git_push = true` when the vault is a git repository with an upstream. After each run the tool commits changes under the output folder, and only those, then runs `git pull --rebase` and `git push`. Other edits in the vault are left alone. A failed push keeps the pages committed locally and is retried on the next run.

## Use

```bash
git-summary run                                   # every missing day up to yesterday
git-summary run --date 2026-11-12 --force         # regenerate one day
git-summary run --from 2026-11-01 --to 2026-11-07 # fill missing days in a range
git-summary run --dry-run                         # commit counts and token estimates, no model calls
git-summary run --save-prompts /tmp/prompts       # keep the exact prompts and responses
git-summary schedule install --time 08:00         # daily job (launchd on macOS, cron on Linux)
git-summary schedule remove
```

Existing pages are never overwritten without `--force`, and `--force` requires an explicit date or range.

Exit codes: `0` everything written, `1` a day failed, was partial, or the push failed, `2` config or usage error. Logs go to `~/.local/state/git-summary/git-summary.log`.

## Privacy

Commit metadata and patches from the configured repositories are sent to Anthropic, through either the API or Claude Code, to write each page. Do not point the tool at code you are not allowed to send there. Use `omit_patch` to keep specific paths' contents out of the prompt; those files are described by line counts only.

The generated pages describe your code in detail. Treat the output folder as being as sensitive as the repositories themselves.

## Development

```bash
make test     # pytest
make lint     # ruff check + format check
```

The design is described in [docs/spec](docs/spec/Daily%20Git%20Summary%20build%20spec.md).

## Licence

[MIT](LICENSE)
