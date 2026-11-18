# git-summary

Writes one Markdown page per day into an Obsidian vault, summarising what landed on the default branch of a set of git repositories. Claude Sonnet reads the actual patches. Spec: [docs/spec](docs/spec/Daily%20Git%20Summary%20build%20spec.md).

## Install

```bash
uv tool install .            # or: pipx install .
```

Requires Python 3.11+ and git 2.37+.

## Configure

Create `~/.config/git-summary/config.toml` (see the spec for every key):

```toml
vault_path = "/path/to/vault"

[model]
backend = "claude_code"      # or "api"
name = "claude-sonnet-5-5"

[[repos]]
name = "code"
url = "git@github.com:ORG/code.git"

[[repos]]
name = "infra"
path = "/Users/me/src/infra"
```

To keep the vault in GitHub, make it a git repository with an upstream and set `vault_git_push = true`. After each run the tool commits the changes in the output folder, and only those, then runs `git pull --rebase` and `git push`. A failed push leaves the pages committed locally and is retried on the next run.

`prompt.md` and `risk_checklist.md` are copied beside the config on first run; edit them freely.

For the `api` backend, the key comes from `ANTHROPIC_API_KEY`, or on macOS from the login Keychain so scheduled runs can find it:

```bash
security add-generic-password -s git-summary -a anthropic -w
```

## Use

```bash
git-summary run                                   # every missing day through yesterday
git-summary run --date 2026-11-12 --force         # regenerate one day
git-summary run --from 2026-11-01 --to 2026-11-07
git-summary run --dry-run                         # commit counts and token estimates only
git-summary schedule install --time 08:00         # launchd on macOS, cron on Linux
git-summary schedule remove
```

Logs: `~/.local/state/git-summary/git-summary.log`.

## Develop

```bash
make test
make lint
```
