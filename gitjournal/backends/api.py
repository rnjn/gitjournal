import os
import subprocess
import sys
from collections.abc import Callable, Mapping

import anthropic

from gitjournal.backends import BackendError, RetryableError
from gitjournal.budget import OUTPUT_RESERVE

FALLBACK_BETA = "server-side-fallback-2026-07-01"
KEYCHAIN_SERVICE = "gitjournal"
KEYCHAIN_ACCOUNT = "anthropic"
REQUEST_TIMEOUT = 900.0


def keychain_key() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                KEYCHAIN_ACCOUNT,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def resolve_api_key(
    env: Mapping[str, str] = os.environ, keychain: Callable[[], str | None] = keychain_key
) -> str | None:
    return env.get("ANTHROPIC_API_KEY") or keychain()


def _translate(e: anthropic.APIError) -> BackendError:
    if isinstance(e, anthropic.APIConnectionError | anthropic.RateLimitError):
        return RetryableError(f"{type(e).__name__}: {e}")
    if isinstance(e, anthropic.APIStatusError) and (e.status_code >= 500 or e.status_code == 408):
        return RetryableError(f"{type(e).__name__} {e.status_code}: {e.message}")
    return BackendError(f"{type(e).__name__}: {e}")


class ApiBackend:
    def __init__(self, model: str, client=None):
        self.model = model
        if client is None:
            key = resolve_api_key()
            client = anthropic.Anthropic(
                **({"api_key": key} if key else {}), max_retries=0, timeout=REQUEST_TIMEOUT
            )
        self.client = client

    def summarise(self, system: str, user: str) -> str:
        try:
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=OUTPUT_RESERVE,
                system=system,
                messages=[{"role": "user", "content": user}],
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                msg = stream.get_final_message()
        except anthropic.APIError as e:
            raise _translate(e) from e
        if msg.stop_reason == "refusal":
            raise BackendError("model refused the request")
        return "".join(b.text for b in msg.content if b.type == "text")

    def count_tokens(self, system: str, user: str) -> int:
        try:
            result = self.client.messages.count_tokens(
                model=self.model,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.APIError as e:
            raise _translate(e) from e
        return result.input_tokens

    def context_limit(self) -> int:
        try:
            return self.client.models.retrieve(self.model).max_input_tokens
        except anthropic.APIError as e:
            raise _translate(e) from e
