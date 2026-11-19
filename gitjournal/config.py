import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CONFIG_PATH = Path("~/.config/gitjournal/config.toml").expanduser()
BACKENDS = ("api", "claude_code")
PROMPT_FILES = ("prompt.md", "risk_checklist.md")

DEFAULT_OMIT_PATCH = [
    "**/package-lock.json",
    "**/yarn.lock",
    "**/pnpm-lock.yaml",
    "**/go.sum",
    "**/Cargo.lock",
    "**/poetry.lock",
    "**/uv.lock",
    "**/*.min.js",
    "**/*.min.css",
    "**/*.map",
    "**/__snapshots__/**",
    "**/*.snap",
    "**/vendor/**",
    "**/node_modules/**",
    "**/dist/**",
    "**/*.pb.go",
    "**/*_pb2.py",
    "**/*.generated.*",
]


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class RepoConfig:
    name: str
    url: str | None = None
    path: Path | None = None
    branch: str | None = None
    web_url: str | None = None


@dataclass(frozen=True)
class ModelConfig:
    backend: str = "api"
    name: str = "claude-sonnet-5-5"
    max_input_tokens: int = 0


@dataclass(frozen=True)
class Config:
    vault_path: Path
    repos: list[RepoConfig]
    config_dir: Path
    timezone: str = "Asia/Kolkata"
    output_folder: str = "Git Journal"
    cache_dir: Path = Path("~/.cache/gitjournal/repos").expanduser()
    log_file: Path = Path("~/.local/state/gitjournal/gitjournal.log").expanduser()
    first_run_backfill_days: int = 30
    vault_git_push: bool = False
    model: ModelConfig = field(default_factory=ModelConfig)
    omit_patch: list[str] = field(default_factory=lambda: list(DEFAULT_OMIT_PATCH))

    @property
    def output_dir(self) -> Path:
        return self.vault_path / self.output_folder

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _repo(raw: dict) -> RepoConfig:
    name = raw.get("name")
    if not name:
        raise ConfigError("each [[repos]] entry needs a name")
    if ("url" in raw) == ("path" in raw):
        raise ConfigError(f"repo {name!r} must have exactly one of url or path")
    return RepoConfig(
        name=name,
        url=raw.get("url"),
        path=_path(raw["path"]) if "path" in raw else None,
        branch=raw.get("branch"),
        web_url=raw.get("web_url"),
    )


def load_config(path: Path) -> Config:
    path = Path(path).expanduser()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {path}: {e}") from e

    if "vault_path" not in raw:
        raise ConfigError("vault_path is required")

    repos = [_repo(r) for r in raw.get("repos", [])]
    if not repos:
        raise ConfigError("at least one [[repos]] entry is required")
    names = [r.name for r in repos]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ConfigError(f"duplicate repo names: {', '.join(dupes)}")

    model_raw = raw.get("model", {})
    model = ModelConfig(
        backend=model_raw.get("backend", ModelConfig.backend),
        name=model_raw.get("name", ModelConfig.name),
        max_input_tokens=int(model_raw.get("max_input_tokens", 0)),
    )
    if model.backend not in BACKENDS:
        raise ConfigError(f"model.backend must be one of {', '.join(BACKENDS)}")

    timezone = raw.get("timezone", Config.timezone)
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise ConfigError(f"unknown timezone: {timezone}") from e

    kwargs = {}
    for key in ("cache_dir", "log_file"):
        if key in raw:
            kwargs[key] = _path(raw[key])
    if "output_folder" in raw:
        kwargs["output_folder"] = raw["output_folder"]
    if "first_run_backfill_days" in raw:
        kwargs["first_run_backfill_days"] = int(raw["first_run_backfill_days"])
    if "vault_git_push" in raw:
        if not isinstance(raw["vault_git_push"], bool):
            raise ConfigError("vault_git_push must be true or false")
        kwargs["vault_git_push"] = raw["vault_git_push"]
    if "omit_patch" in raw.get("filters", {}):
        kwargs["omit_patch"] = list(raw["filters"]["omit_patch"])

    return Config(
        vault_path=_path(raw["vault_path"]),
        repos=repos,
        config_dir=path.parent,
        timezone=timezone,
        model=model,
        **kwargs,
    )


def ensure_prompt_files(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    defaults = files("gitjournal") / "defaults"
    for name in PROMPT_FILES:
        target = config_dir / name
        if not target.exists():
            target.write_text((defaults / name).read_text(encoding="utf-8"), encoding="utf-8")


def load_system_prompt(config_dir: Path) -> str:
    parts = [(config_dir / name).read_text(encoding="utf-8").strip() for name in PROMPT_FILES]
    return "\n\n".join(parts) + "\n"
