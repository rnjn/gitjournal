from pathlib import Path

import pytest

from git_summary.config import DEFAULT_OMIT_PATCH, ConfigError, load_config

MINIMAL = """
vault_path = "{vault}"

[[repos]]
name = "code"
url = "git@github.com:org/code.git"
"""


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(text.replace("{vault}", str(tmp_path / "vault")))
    return p


def test_minimal_config_gets_defaults(tmp_path):
    cfg = load_config(write(tmp_path, MINIMAL))
    assert cfg.timezone == "Asia/Kolkata"
    assert cfg.vault_path == tmp_path / "vault"
    assert cfg.output_folder == "Git Summary"
    assert cfg.output_dir == tmp_path / "vault" / "Git Summary"
    assert cfg.first_run_backfill_days == 30
    assert cfg.vault_git_push is False
    assert cfg.model.backend == "api"
    assert cfg.model.name == "claude-sonnet-5-5"
    assert cfg.model.max_input_tokens == 0
    assert cfg.omit_patch == DEFAULT_OMIT_PATCH
    assert cfg.config_dir == tmp_path
    assert cfg.cache_dir == Path("~/.cache/git-summary/repos").expanduser()
    [repo] = cfg.repos
    assert repo.name == "code"
    assert repo.url == "git@github.com:org/code.git"
    assert repo.path is None
    assert repo.branch is None
    assert repo.web_url is None


def test_full_config(tmp_path):
    text = """
timezone = "Asia/Kolkata"
vault_path = "{vault}"
output_folder = "Daily"
cache_dir = "~/c"
log_file = "~/l.log"
first_run_backfill_days = 5

[model]
backend = "claude_code"
name = "claude-sonnet-5-5"
max_input_tokens = 1000

[[repos]]
name = "code"
url = "git@github.com:org/code.git"
branch = "trunk"
web_url = "https://github.com/org/code"

[[repos]]
name = "infra"
path = "~/src/infra"

[filters]
omit_patch = ["**/*.lock"]
"""
    cfg = load_config(write(tmp_path, text))
    assert cfg.output_dir == tmp_path / "vault" / "Daily"
    assert cfg.cache_dir == Path("~/c").expanduser()
    assert cfg.log_file == Path("~/l.log").expanduser()
    assert cfg.first_run_backfill_days == 5
    assert cfg.model.backend == "claude_code"
    assert cfg.model.max_input_tokens == 1000
    assert [r.name for r in cfg.repos] == ["code", "infra"]
    assert cfg.repos[0].branch == "trunk"
    assert cfg.repos[0].web_url == "https://github.com/org/code"
    assert cfg.repos[1].path == Path("~/src/infra").expanduser()
    assert cfg.omit_patch == ["**/*.lock"]


@pytest.mark.parametrize(
    "repo_block, message",
    [
        ('name = "x"', "exactly one of"),
        ('name = "x"\nurl = "u"\npath = "p"', "exactly one of"),
        ('url = "u"', "name"),
    ],
)
def test_repo_source_errors(tmp_path, repo_block, message):
    text = 'vault_path = "{vault}"\n[[repos]]\n' + repo_block
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_duplicate_repo_names(tmp_path):
    text = MINIMAL + '\n[[repos]]\nname = "code"\npath = "/x"\n'
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(write(tmp_path, text))


def test_no_repos(tmp_path):
    with pytest.raises(ConfigError, match="repos"):
        load_config(write(tmp_path, 'vault_path = "{vault}"\n'))


def test_missing_vault_path(tmp_path):
    with pytest.raises(ConfigError, match="vault_path"):
        load_config(write(tmp_path, '[[repos]]\nname = "a"\npath = "/x"\n'))


def test_bad_backend(tmp_path):
    with pytest.raises(ConfigError, match="backend"):
        load_config(write(tmp_path, MINIMAL + '\n[model]\nbackend = "gpt"\n'))


def test_bad_timezone(tmp_path):
    with pytest.raises(ConfigError, match="timezone"):
        load_config(write(tmp_path, 'timezone = "Mars/Base"\n' + MINIMAL))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_invalid_toml(tmp_path):
    with pytest.raises(ConfigError, match="TOML"):
        load_config(write(tmp_path, "vault_path = "))


def test_prompt_files_copied_on_first_run_and_not_overwritten(tmp_path):
    from git_summary.config import ensure_prompt_files, load_system_prompt

    ensure_prompt_files(tmp_path)
    prompt = tmp_path / "prompt.md"
    checklist = tmp_path / "risk_checklist.md"
    assert "<narrative>" in prompt.read_text()
    assert "sub-bullet" in prompt.read_text()
    assert "migrations" in checklist.read_text().lower()

    checklist.write_text("- my own rule\n")
    ensure_prompt_files(tmp_path)
    assert checklist.read_text() == "- my own rule\n"

    system = load_system_prompt(tmp_path)
    assert system.startswith(prompt.read_text().rstrip())
    assert system.rstrip().endswith("- my own rule")


def test_vault_git_push(tmp_path):
    cfg = load_config(write(tmp_path, "vault_git_push = true\n" + MINIMAL))
    assert cfg.vault_git_push is True


def test_vault_git_push_must_be_bool(tmp_path):
    with pytest.raises(ConfigError, match="vault_git_push"):
        load_config(write(tmp_path, 'vault_git_push = "yes"\n' + MINIMAL))
