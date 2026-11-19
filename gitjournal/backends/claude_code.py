import json
import subprocess
import tempfile

from gitjournal.backends import BackendError, RetryableError
from gitjournal.budget import char_estimate

CALL_TIMEOUT = 900
DOCUMENTED_CONTEXT_LIMIT = 1_000_000


class ClaudeCodeBackend:
    def __init__(self, model: str, runner=subprocess.run, executable: str = "claude"):
        self.model = model
        self.runner = runner
        self.executable = executable

    def summarise(self, system: str, user: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".md", encoding="utf-8") as f:
            f.write(system)
            f.flush()
            cmd = [
                self.executable,
                "-p",
                "--model",
                self.model,
                "--tools",
                "",
                "--system-prompt-file",
                f.name,
                "--output-format",
                "json",
                "--no-session-persistence",
                "--strict-mcp-config",
            ]
            try:
                out = self.runner(
                    cmd, input=user, capture_output=True, text=True, timeout=CALL_TIMEOUT
                )
            except FileNotFoundError as e:
                raise BackendError(f"{self.executable} not found on PATH") from e
            except subprocess.TimeoutExpired as e:
                raise RetryableError(f"claude timed out after {CALL_TIMEOUT}s") from e
        if out.returncode != 0:
            detail = out.stderr.strip()
            try:
                detail = str(json.loads(out.stdout).get("result")) or detail
            except (json.JSONDecodeError, AttributeError):
                detail = detail or out.stdout.strip()
            raise RetryableError(f"claude exited {out.returncode}: {detail[:500]}")
        try:
            result = json.loads(out.stdout)
        except json.JSONDecodeError as e:
            raise RetryableError("claude returned non-JSON output") from e
        if result.get("is_error"):
            raise RetryableError(f"claude reported an error: {str(result.get('result'))[:500]}")
        return result.get("result", "")

    def count_tokens(self, system: str, user: str) -> int:
        return char_estimate(system, user)

    def context_limit(self) -> int:
        return DOCUMENTED_CONTEXT_LIMIT
