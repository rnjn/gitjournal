import json
import subprocess
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from gitjournal.backends import BackendError, RetryableError, make_backend, with_retries
from gitjournal.backends.api import ApiBackend, resolve_api_key
from gitjournal.backends.claude_code import ClaudeCodeBackend
from gitjournal.config import ModelConfig
from gitjournal.render import ResponseError


def test_with_retries_succeeds_after_transient_failures():
    calls, sleeps = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise RetryableError("busy")
        return "ok"

    assert with_retries(fn, sleep=sleeps.append) == "ok"
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]


def test_with_retries_retries_malformed_responses():
    calls = []

    def fn():
        calls.append(1)
        raise ResponseError("missing <people>")

    with pytest.raises(ResponseError):
        with_retries(fn, sleep=lambda s: None)
    assert len(calls) == 3


def test_with_retries_does_not_retry_permanent_errors():
    calls = []

    def fn():
        calls.append(1)
        raise BackendError("bad key")

    with pytest.raises(BackendError):
        with_retries(fn, sleep=lambda s: None)
    assert len(calls) == 1


class StubStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.message


def stub_client(message=None, error=None):
    seen = {}

    def stream(**kwargs):
        seen.update(kwargs)
        if error:
            raise error
        return StubStream(message)

    client = SimpleNamespace(
        beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)),
        messages=SimpleNamespace(
            count_tokens=lambda **kw: SimpleNamespace(input_tokens=1234, kw=seen.update(count=kw))
        ),
        models=SimpleNamespace(retrieve=lambda mid: SimpleNamespace(max_input_tokens=1_000_000)),
    )
    return client, seen


def message(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        stop_reason=stop_reason,
    )


def test_api_backend_summarise_request_shape():
    client, seen = stub_client(message("<narrative>x</narrative>"))
    backend = ApiBackend("claude-sonnet-5-5", client=client)
    assert backend.summarise("SYS", "USER") == "<narrative>x</narrative>"
    assert seen["model"] == "claude-sonnet-5-5"
    assert seen["system"] == "SYS"
    assert seen["messages"] == [{"role": "user", "content": "USER"}]
    assert seen["fallbacks"] == "default"
    assert seen["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in seen and "thinking" not in seen


def test_api_backend_count_and_context_limit():
    client, seen = stub_client()
    backend = ApiBackend("claude-sonnet-5-5", client=client)
    assert backend.count_tokens("SYS", "USER") == 1234
    assert seen["count"]["system"] == "SYS"
    assert backend.context_limit() == 1_000_000


def test_api_backend_refusal_is_permanent():
    client, _ = stub_client(message("", stop_reason="refusal"))
    with pytest.raises(BackendError, match="refus") as exc:
        ApiBackend("m", client=client).summarise("s", "u")
    assert not isinstance(exc.value, RetryableError)


def _status_error(cls, status):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=req), body=None)


@pytest.mark.parametrize(
    "error",
    [
        _status_error(anthropic.RateLimitError, 429),
        _status_error(anthropic.InternalServerError, 500),
        _status_error(anthropic.APIStatusError, 529),
        anthropic.APITimeoutError(httpx2.Request("POST", "https://x")),
        anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")),
    ],
)
def test_api_backend_transient_errors_are_retryable(error):
    client, _ = stub_client(error=error)
    with pytest.raises(RetryableError):
        ApiBackend("m", client=client).summarise("s", "u")


def test_api_backend_auth_error_is_permanent():
    client, _ = stub_client(error=_status_error(anthropic.AuthenticationError, 401))
    with pytest.raises(BackendError) as exc:
        ApiBackend("m", client=client).summarise("s", "u")
    assert not isinstance(exc.value, RetryableError)


def test_resolve_api_key_prefers_env():
    assert resolve_api_key({"ANTHROPIC_API_KEY": "env"}, lambda: "kc") == "env"


def test_resolve_api_key_falls_back_to_keychain():
    assert resolve_api_key({}, lambda: "kc") == "kc"
    assert resolve_api_key({}, lambda: None) is None


class FakeRunner:
    def __init__(self, stdout="", returncode=0, exc=None):
        self.stdout, self.returncode, self.exc = stdout, returncode, exc
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, "err text")


def test_claude_code_command_and_result():
    runner = FakeRunner(json.dumps({"is_error": False, "result": "<narrative>y</narrative>"}))
    backend = ClaudeCodeBackend("claude-sonnet-5-5", runner=runner)
    assert backend.summarise("SYS", "USER") == "<narrative>y</narrative>"
    [(cmd, kwargs)] = runner.calls
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert "--no-session-persistence" in cmd
    assert "--system-prompt-file" in cmd
    assert kwargs["input"] == "USER"


def test_claude_code_system_prompt_file_contents():
    seen = {}

    def runner(cmd, **kwargs):
        with open(cmd[cmd.index("--system-prompt-file") + 1]) as f:
            seen["system"] = f.read()
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": "r"}), "")

    ClaudeCodeBackend("m", runner=runner).summarise("SYS PROMPT", "u")
    assert seen["system"] == "SYS PROMPT"


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(returncode=1),
        FakeRunner(json.dumps({"is_error": True, "result": "overloaded"})),
        FakeRunner("not json"),
        FakeRunner(exc=subprocess.TimeoutExpired("claude", 900)),
    ],
)
def test_claude_code_failures_are_retryable(runner):
    with pytest.raises(RetryableError):
        ClaudeCodeBackend("m", runner=runner).summarise("s", "u")


def test_claude_code_missing_binary_is_permanent():
    runner = FakeRunner(exc=FileNotFoundError("claude"))
    with pytest.raises(BackendError) as exc:
        ClaudeCodeBackend("m", runner=runner).summarise("s", "u")
    assert not isinstance(exc.value, RetryableError)


def test_claude_code_counts_by_characters():
    backend = ClaudeCodeBackend("m", runner=FakeRunner())
    assert backend.count_tokens("abc", "abcdef") == 4


def test_make_backend_selects_by_name():
    model = ModelConfig(backend="claude_code", name="claude-sonnet-5-5")
    assert isinstance(make_backend(model, None), ClaudeCodeBackend)
    assert isinstance(make_backend(model, "api", client=stub_client()[0]), ApiBackend)


def test_claude_code_nonzero_exit_reports_json_result():
    out = json.dumps({"is_error": True, "result": "Prompt is too long"})
    with pytest.raises(RetryableError, match="Prompt is too long"):
        ClaudeCodeBackend("m", runner=FakeRunner(out, returncode=1)).summarise("s", "u")
