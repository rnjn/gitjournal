import time
from collections.abc import Callable
from typing import Protocol, TypeVar

from git_summary.config import ModelConfig
from git_summary.render import ResponseError

T = TypeVar("T")
ATTEMPTS = 3
BASE_DELAY = 2.0


class BackendError(Exception):
    pass


class RetryableError(BackendError):
    pass


class Backend(Protocol):
    model: str

    def summarise(self, system: str, user: str) -> str: ...

    def count_tokens(self, system: str, user: str) -> int: ...

    def context_limit(self) -> int: ...


def with_retries(
    fn: Callable[[], T],
    attempts: int = ATTEMPTS,
    base_delay: float = BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    for attempt in range(attempts):
        try:
            return fn()
        except (RetryableError, ResponseError):
            if attempt == attempts - 1:
                raise
            sleep(base_delay * 2**attempt)
    raise AssertionError("unreachable")


def make_backend(model: ModelConfig, override: str | None, **kwargs) -> Backend:
    name = override or model.backend
    if name == "api":
        from git_summary.backends.api import ApiBackend

        return ApiBackend(model.name, **kwargs)
    if name == "claude_code":
        from git_summary.backends.claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend(model.name, **kwargs)
    raise BackendError(f"unknown backend: {name}")
