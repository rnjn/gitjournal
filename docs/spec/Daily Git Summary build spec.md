# Daily Git Summary: build spec

Nov 16, 2026 · @rnjn

## Overview

A Python command-line tool that writes one Markdown page per calendar day into an Obsidian vault, describing what landed on `main` across a configured set of git repositories. It reads the actual patches, not just commit messages, and uses Claude Sonnet to turn them into a narrative.

The only reader is the repo owner. Pages can be dense, technical and candid, and they name commit authors freely.

Each page serves three goals:

- Show what moved forward across the product.
- Surface risky changes such as migrations, config defaults and removed tests.
- Show who is working on what.

A run does the following for every day that needs a page:

1. Fetch each configured repository.
2. Select the commits on the default branch whose committer date falls in that day (IST).
3. Build one prompt containing every commit's author, message and patch.
4. Call Sonnet once and receive the page body.
5. Validate the citations, add frontmatter, and write `Git Summary/YYYY-MM-DD.md`.

## Scope

Version 1 covers five kinds of repository: the code monorepo, the infra monorepo, the website, the docs, and the open source SDKs. All are read from the default branch only.

In scope:

- Every commit on the default branch, including bot and automated commits, treated like any other commit.
- Runs on the owner's laptop, scheduled each morning and on demand.
- One page per IST calendar day, with backfill of missed days.

Out of scope for v1:

- Pull requests, branches other than the default, tags and releases.
- Grouping work by theme across repositories. Each repo is described on its own.
- Continuity between days. Each page stands alone and is generated without earlier pages as input.
- Author identity merging. Names appear exactly as git records them.
- Delivery by email or chat, and any hosted service.

## Configuration

All behaviour is driven by one TOML file, default `~/.config/git-summary/config.toml`, overridable with `--config`. Nothing is hard-coded to the laptop, so the same code can later run in a GitHub Action with a different config.

```toml
timezone = "Asia/Kolkata"
vault_path = "/path/to/vault"
output_folder = "Git Summary"
cache_dir = "~/.cache/git-summary/repos"
log_file = "~/.local/state/git-summary/git-summary.log"
first_run_backfill_days = 30

[model]
backend = "api"            # "api" or "claude_code"
name = "claude-sonnet-5-5"
max_input_tokens = 0        # 0 = use the model's context limit

[[repos]]
name = "code"
url = "git@github.com:ORG/code.git"     # tool keeps a bare clone in cache_dir

[[repos]]
name = "infra"
path = "/Users/me/src/infra"            # existing local clone

[filters]
omit_patch = [
  "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml",
  "**/go.sum", "**/Cargo.lock", "**/poetry.lock", "**/uv.lock",
  "**/*.min.js", "**/*.min.css", "**/*.map",
  "**/__snapshots__/**", "**/*.snap",
  "**/vendor/**", "**/node_modules/**", "**/dist/**",
  "**/*.pb.go", "**/*_pb2.py", "**/*.generated.*",
]
```

Rules:

- Each `[[repos]]` entry has a `name` and exactly one of `url` or `path`. A missing or doubled source is a config error reported at startup.
- For `url` repos the tool creates and maintains a bare clone under `cache_dir`. A plain `git clone --bare` has no `origin/*` refs and no fetch refspec, so after cloning the tool sets `remote.origin.fetch` to `+refs/heads/*:refs/remotes/origin/*` and fetches, so both kinds of repo read `origin/<branch>` the same way. For `path` repos it runs `git fetch` in place and reads `origin/<default branch>` only. It never checks out, resets or modifies a working tree.
- The default branch is detected per repo from `origin/HEAD`, falling back to `main`, then `master`. An optional `branch` key overrides detection.
- The GitHub web URL for commit links is derived from the `origin` remote (SSH and HTTPS forms). An optional `web_url` key overrides it.
- The API key is read from the `ANTHROPIC_API_KEY` environment variable and never from the config file. Because launchd and cron do not load the shell environment, on macOS the tool falls back to the login Keychain (`security find-generic-password -s git-summary -a anthropic -w`) when the variable is unset. The key is only required for the `api` backend.
- Two prompt files live beside the config and are user-editable: `prompt.md` (instructions and page layout) and `risk_checklist.md` (the "Worth a look" criteria). The tool ships defaults and copies them on first run if absent.

## Days and commit selection

A day is midnight to midnight in `Asia/Kolkata`, and a commit belongs to the day of its committer date. Committer date is used because main is linear and rebased, which makes it the closest value git holds to "when this landed".

**Which commits.** For day D, per repo, after a fetch:

```bash
git log origin/<branch> --first-parent --reverse \
  --since="D 00:00:00 +0530" --until="D+1 00:00:00 +0530" \
  --format='%H%x00%h%x00%an%x00%cI%x00%s%x00%b%x1e'
```

`--since` and `--until` filter on committer date, but git treats `--until` as inclusive (verified on git 2.54: a commit at exactly D+1 00:00:00 is returned for day D), and `--since` stops the history walk at the first commit older than the bound, so a single out-of-order committer date hides everything below it (also verified). The tool therefore uses `--since-as-filter` (git 2.37 or later), which filters without stopping the walk, and treats the git range only as a coarse pre-filter, widened by one day on each side (`--since-as-filter="D-1 00:00:00 +0530" --until="D+2 00:00:00 +0530"`). The authoritative rule is applied in Python on the parsed `%cI` value: `start <= committer_time < end`, with `start` and `end` as timezone-aware IST datetimes. A commit at exactly midnight belongs to the next day. Main is expected to be linear; if a merge commit does appear, it is included as one commit with its patch taken against its first parent, and the run does not fail.

**Which days.** The page files are the only state. A day is done when its file exists.

- A normal run targets every date from the start date through yesterday (IST) that has no file. It never writes a page for today.
- The start date is the earliest existing page in the output folder. If the folder is empty, it is yesterday minus `first_run_backfill_days` plus one, giving 30 pages on first run.
- `--from` and `--to` override the range. Existing files in the range are still skipped unless `--force` is given.
- Days are processed oldest first. Each day is independent, so one failed day does not block the others.

**Late commits.** A commit made locally on Monday and pushed on Tuesday carries Monday's committer date, and Monday's page may already exist. To catch this, each run recounts commits for the 3 most recent existing pages and compares against the `commits` value in their frontmatter. On a mismatch it logs a warning naming the date and suggesting `--force`. It does not regenerate on its own.

## What the model reads

The model receives every commit of the day as its own unit: author, message and full patch. There is no size cap per file or per commit in the normal path.

**Per commit**, in chronological order within each repo:

- Short SHA, author name exactly as git records it (`%an`), committer time in IST.
- Subject and full body.
- Areas touched. An area is the first path segment of a changed file; files at the repo root belong to the area `(root)`. The tool computes this, with no hand-written map.
- `git show --numstat` for all files.
- The patch from `git show --format= --patch --no-color -M <sha>`.

**Low-signal files.** For any file matching `filters.omit_patch`, the patch is replaced by one line such as `[patch omitted: lockfile, +812 -640]`. The file still appears in the numstat. Binary files show git's own "Binary files differ" line.

**Prompt layout.** The system prompt is `prompt.md` followed by `risk_checklist.md`. The user message holds the date, then one block per repo with its name, web URL, a per-area commit count, and the commits. Repos with no commits that day are listed in a single line so the model can say so. Use clearly delimited tags per repo and per commit so patches containing Markdown or prompt-like text cannot be mistaken for instructions; the system prompt states that commit content is data.

**When the day does not fit.** Before calling, estimate input tokens (the API's token counting endpoint for the `api` backend, a characters-divided-by-3 estimate for `claude_code`). The budget is the model's context limit minus a 16,000 token reserve for output, or `max_input_tokens` if set.

1. Fits: one call for the whole day. This is the expected case at 10 to 50 commits.
2. Does not fit: one call per repo. Each call returns the same three parts (narrative, worth a look, people) and the tool concatenates them under the shared headings, in config order.
3. A single repo still does not fit: replace that repo's largest file patches with their numstat line, largest first, until it fits. The page states which files were reduced.

The developer should confirm the current context limit for the configured model from Anthropic's documentation and not hard-code a remembered value.

## Model invocation

The model is Claude Sonnet, called through one of two backends selected by `model.backend`. Both sit behind a single interface, `summarise(system: str, user: str) -> str`, so the rest of the code does not know which is in use.

- **`api`**: the Anthropic Python SDK, Messages API, model name from config, key from `ANTHROPIC_API_KEY`. This is the backend the later GitHub Action will use.
- **`claude_code`**: Claude Code in its non-interactive print mode as a subprocess, using the owner's existing login. The prompt goes in on stdin, the model is selected by flag, and all tools are disabled so the call is pure text in, text out. The developer should confirm the exact flags against the current Claude Code documentation.

**Response contract.** The model returns three tagged parts and nothing else: `<narrative>`, `<worth_a_look>` and `<people>`. The tool parses these, which is what makes per-repo concatenation and the risk-flag count possible. A response missing any tag counts as a failed call.

**Retries.** Up to 3 attempts per call with exponential backoff, for rate limits, timeouts, server errors and malformed responses. After that the day is treated as failed.

## The daily page

Each day is written to `<vault_path>/Git Summary/YYYY-MM-DD.md`, in one flat folder, using a temp file and rename so a crash never leaves a half-written page.

**Frontmatter**

```yaml
---
date: 2026-11-15
status: ok                 # ok | empty | partial
repos: [code, infra, website, docs, sdk-python]
repos_missing: []
commits: 23
authors: ["Asha Rao", "dependabot[bot]", "Vikram N"]
risk_flags: 2
model: claude-sonnet-5-5
generated_at: 2026-11-16T08:00:12+05:30
tags: [git-summary]
---
```

`repos` lists repositories that were read successfully, whether or not they had commits. `status`, `repos_missing`, `generated_at` and `tags` go beyond the fields originally requested; they support the partial-page and late-commit rules.

**Body layout**, in this order:

1. `# Git summary: Sunday 15 November 2026`
2. `## Narrative`, with a `###` heading per repo that had commits. Within a repo the prose is organised by area. Length is proportional to activity. Trivial commits (typos, formatting, small version bumps) are grouped into one closing line per repo, still with their SHAs. Repos with no commits are named in one line at the end.
3. `## Worth a look`, one bullet per flagged change: what changed, why it deserves attention, the author, the SHA. If nothing qualifies, the single line "Nothing flagged." `risk_flags` is the number of bullets.
4. `## People`, one short entry per author name: the areas they touched and the gist of their work, with SHAs.

**Style rules** (in `prompt.md`): plain, technical prose for a reader who knows the codebase. Past tense. No praise, no hype, no closing summary line. Describe what the patch shows; where the message claims something the patch does not support, say so. Do not guess at intent beyond the evidence.

**Citations.** Every claim is followed by the short SHA of the commit it rests on, linked to GitHub. The model writes bare markers such as `[a1b2c3d]`; the tool rewrites each into `[a1b2c3d](https://github.com/ORG/REPO/commit/<full sha>)`. The model never writes URLs.

- A cited SHA that is not in the day's commit set is left unlinked and logged as a warning.
- Every commit of the day must be cited at least once. Any that are not get listed by the tool in a final line, "Not mentioned above:", with linked SHAs and subjects.

**Default "Worth a look" checklist** (`risk_checklist.md`, editable):

- Database or schema migrations, and changes to retention or TTL settings.
- Changed defaults in config, feature flags or environment variables.
- Tests deleted, skipped or disabled; CI checks loosened.
- Infra changes affecting production: resources destroyed or replaced, scaling limits, networking, IAM and secrets.
- Dependency major-version bumps and new dependencies.
- Changes to public surfaces: API contracts, SDK interfaces, ingest formats.
- Reverts, and commits whose patch does not match their message.
- Unusually large commits, or one commit touching many areas.

**Empty days.** If every repo was read and none had commits, write a page with `status: empty`, `commits: 0`, and the body "No commits on main in any repository." No model call is made.

**Partial days.** If some repos could not be read, write the page from the ones that could, with `status: partial`, the failed names in `repos_missing`, and a callout at the top naming each missing repo, the error, and the exact `--force` command to regenerate. If no repo could be read, or the model call fails, write no file; the day is retried on the next run. If some repos failed and every repo that was read had no commits, write a `status: partial` page with `commits: 0`, the callout, and the empty-day body; no model call is made.

## Commands, scheduling and reruns

The tool installs as a single command, `git-summary`, and the scheduled job runs exactly the same command a person would.

| Command | Behaviour |
| --- | --- |
| `git-summary run` | Generate every missing day through yesterday. Skips days whose file exists. |
| `git-summary run --date 2026-11-12` | Target one day. |
| `git-summary run --from 2026-11-01 --to 2026-11-07` | Target a range, inclusive. |
| `... --force` | Overwrite existing pages. Only valid together with `--date` or `--from`/`--to`. |
| `... --dry-run` | Fetch, select commits and print per-day commit counts and estimated tokens. No generation call and no files written; the `api` backend may call the token counting endpoint. |
| `... --backend api` | Override `model.backend` for this run. |
| `git-summary schedule install --time 08:00` | Install the daily job. |
| `git-summary schedule remove` | Remove it. |

**Rerun rule.** An existing page is never overwritten unless `--force` is given with an explicit date or range. `--force` without one is an error, so the whole history cannot be regenerated by accident.

**Scheduling.** On macOS, `schedule install` writes a launchd agent; on Linux, a crontab entry. The default time is 08:00 local, which is an assumption to confirm. No wake-up catch-up logic is needed: a missed morning is repaired by the next run, scheduled or manual, because that run generates every missing day.

The launchd plist and crontab entry set `PATH` to the directories holding `git` and, for the `claude_code` backend, `claude`, resolved at install time, since scheduled jobs do not inherit the shell's `PATH`.

**Concurrency.** A lock file prevents a manual run and a scheduled run from overlapping. The second one exits immediately with a logged message and exit code `0`, so the scheduler does not record a failure.

**Exit codes.** `0` when every targeted day was written in full (or the run was skipped because another holds the lock), `1` when any day failed or was written partial, `2` for config or usage errors.

## Failures and logging

Failures are reported in the log file only. There are no notifications and no error notes written into the vault, apart from the callout on a partial page.

| Situation | Result |
| --- | --- |
| One or more repos fail to fetch or read, others succeed | Partial page written, with a callout. Stays partial until rerun with `--force`. |
| Every repo fails | No file. Retried next run. |
| Model call fails after 3 attempts | No file for that day. Retried next run. Other days continue. |
| Day does not fit in context | Per-repo calls, then the last-resort reduction. Logged at info level. |
| Model cites an unknown SHA, or omits a commit | Page written; warning logged; uncited commits appended by the tool. |
| Commit count for a recent page no longer matches | Warning logged with the `--force` command. |
| Vault path missing or not writable | Run aborts with exit code 2 before any model call. |

**Fetch behaviour.** Each repo is fetched once per run, not once per day, with a 120 second timeout. Git authentication uses whatever the machine already has (SSH agent or credential helper); the tool handles no git credentials itself.

**Log contents.** One line per run start and end, per repo fetch, and per day with commit count, estimated tokens, calls made, and outcome. The log rotates at 5 MB, keeping 3 files. The API key, prompts and patches are never logged. A `--save-prompts DIR` flag writes the exact prompt and raw response for each call to a directory, for debugging prompt changes.

## Build notes and acceptance

Python 3.11 or later, for `tomllib` and `zoneinfo`. Git is driven through `subprocess`, with no git library. The only runtime dependency is the Anthropic SDK. The project is packaged with `pyproject.toml` and installable with `pipx` or `uv tool`.

```text
git_summary/
  cli.py            argument parsing, run loop, exit codes, lock
  config.py         load and validate TOML
  days.py           IST day boundaries, which days to generate
  repos.py          clone, fetch, branch detection, log, show, web URL
  assemble.py       per-commit blocks, area derivation, patch filters
  budget.py         token estimate, per-repo split, last-resort reduction
  backends/api.py
  backends/claude_code.py
  render.py         parse tagged response, frontmatter, page, atomic write
  citations.py      SHA markers to links, unknown and uncited checks
  schedule.py       launchd and cron install and removal
  defaults/prompt.md
  defaults/risk_checklist.md
tests/
```

**Testing.** Tests build throwaway git repos in temp directories with fixed `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE`, and use a fake backend that returns canned tagged responses. No test calls the real model or the network.

**Acceptance criteria**

- [ ] First run against an empty output folder writes exactly 30 pages, ending yesterday (IST).
- [ ] A commit at 23:59:59 IST lands on day D and one at 00:00:00 IST lands on D+1, regardless of the machine's timezone.
- [ ] A second run the same day makes no model calls and writes nothing.
- [ ] Deleting one page and rerunning regenerates only that page.
- [ ] `--force` without a date or range exits with code 2.
- [ ] A day with no commits produces a `status: empty` page and no model call.
- [ ] With one repo unreachable, the page is written with `status: partial`, the repo in `repos_missing`, and a callout containing the regenerate command.
- [ ] Files matching `omit_patch` appear in the numstat with their patch replaced by the omission line.
- [ ] Every short SHA in a page links to the correct repo's commit URL; an invented SHA is unlinked and logged.
- [ ] A commit the model failed to mention appears in "Not mentioned above:".
- [ ] When the estimate exceeds the budget, the tool makes one call per repo and the page has a single set of the three headings.
- [ ] Author names in the page and frontmatter match `git log --format=%an` exactly.
- [ ] Switching `model.backend` between `api` and `claude_code` needs no other change and yields the same page structure.
- [ ] A `path` repo with uncommitted changes and a different branch checked out is left untouched.
- [ ] Adding a commit to an already-summarised recent day produces a logged mismatch warning on the next run.

## Deferred and open

These were raised and deliberately left out of v1. The design should not block them.

- Running as a scheduled GitHub Action and sharing pages with the team. The `api` backend and config-driven paths exist for this.
- Grouping work by theme across repositories.
- Continuity between days, such as feeding recent pages back in or keeping a list of ongoing threads.
- A hand-written area map with descriptions, in place of top-level directories.
- Merging author identities, through `.mailmap` or an alias file.
- Notifications on failure, and delivery by email or Slack.
- Additions to the "Worth a look" checklist, which is already editable without code changes.

Open items to settle before or during the build:

- [ ] Exact repo list: names and URLs or local paths for the code repo, infra repo, website, docs, and each SDK.
- [ ] Scheduled run time. 08:00 local is assumed.
- [ ] Laptop operating system, which decides whether launchd or cron is the primary scheduler to test.
- [ ] Vault path.
