import pytest

from git_summary.vault import VaultError, publish
from tests.gitutil import git, vault_with_remote

FOLDER = "Git Summary"


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    vault_with_remote(v, tmp_path / "remote.git")
    (v / FOLDER).mkdir()
    return v


def remote_log(tmp_path):
    return git(tmp_path / "remote.git", "log", "--format=%s", "main").splitlines()


def write_page(vault, day, text="page\n"):
    (vault / FOLDER / f"{day}.md").write_text(text)


def test_commits_new_pages_and_pushes(tmp_path, vault):
    write_page(vault, "2026-11-15")
    write_page(vault, "2026-11-16")
    assert publish(vault, FOLDER) == "git-summary: 2026-11-15..2026-11-16"
    assert remote_log(tmp_path) == ["git-summary: 2026-11-15..2026-11-16", "init"]
    files = git(tmp_path / "remote.git", "ls-tree", "-r", "--name-only", "main").splitlines()
    assert f"{FOLDER}/2026-11-16.md" in files


def test_single_page_message_and_regenerated_page(tmp_path, vault):
    write_page(vault, "2026-11-16")
    publish(vault, FOLDER)
    write_page(vault, "2026-11-16", "regenerated\n")
    assert publish(vault, FOLDER) == "git-summary: 2026-11-16"
    assert remote_log(tmp_path)[0] == "git-summary: 2026-11-16"


def test_nothing_changed_makes_no_commit(tmp_path, vault):
    assert publish(vault, FOLDER) is None
    assert remote_log(tmp_path) == ["init"]


def test_pushes_earlier_unpushed_commit(tmp_path, vault):
    write_page(vault, "2026-11-16")
    git(vault, "add", "-A")
    git(vault, "commit", "-q", "-m", "left behind")
    assert publish(vault, FOLDER) is None
    assert remote_log(tmp_path)[0] == "left behind"


def test_only_output_folder_is_committed(tmp_path, vault):
    (vault / "notes.md").write_text("mine\n")
    (vault / "README.md").write_text("edited\n")
    git(vault, "add", "README.md")
    write_page(vault, "2026-11-16")
    publish(vault, FOLDER)
    files = git(tmp_path / "remote.git", "ls-tree", "-r", "--name-only", "main").splitlines()
    assert "notes.md" not in files
    assert git(tmp_path / "remote.git", "show", "main:README.md") == "vault"
    assert "M  README.md" in git(vault, "status", "--porcelain")


def test_not_a_repository(tmp_path):
    plain = tmp_path / "plain"
    (plain / FOLDER).mkdir(parents=True)
    with pytest.raises(VaultError, match="not a git repository"):
        publish(plain, FOLDER)


def test_push_failure_keeps_local_commit(tmp_path, vault):
    git(vault, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    write_page(vault, "2026-11-16")
    with pytest.raises(VaultError, match="push"):
        publish(vault, FOLDER)
    assert git(vault, "log", "-1", "--format=%s") == "git-summary: 2026-11-16"
