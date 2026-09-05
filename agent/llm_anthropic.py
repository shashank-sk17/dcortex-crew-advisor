"""Anthropic client — the production backend.

Satisfies `agent.llm.LLM` using the official SDK.

Three things it does that the others cannot:

**Prompt caching.** Our system prompt and tool schemas are byte-identical on
every call and account for nearly all the input tokens. Caching them cuts the
repeated cost by roughly 90% and is what makes a multi-call tool loop
affordable — it is the direct answer to the rate-limit wall we hit elsewhere.
Verify with `usage.cache_read_input_tokens`; if that stays zero across
identical-prefix calls, something upstream is varying the prefix.

**Native tool blocks.** The advisor already speaks `tool_use` / `tool_result`,
so nothing is flattened to text the way the OpenAI-compatible backends need.
Tool results reach the model as structured blocks.

**Adaptive thinking.** `{"type": "adaptive"}` lets the model decide how much
to reason. `budget_tokens` is removed on current models and returns a 400.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

from agent.llm import LLMResponse, StreamEvent, ToolCall

try:
    import anthropic
except ImportError:  # keeps the package importable without the SDK
    anthropic = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-opus-5"


class AnthropicError(RuntimeError):
    pass


def load_api_key() -> str | None:
    """`ANTHROPIC_API_KEY` from the environment, else a gitignored .env."""
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return key
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _to_anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Our schemas are already the Anthropic shape; cache the last one.

    Tools render before the system prompt, so a breakpoint on the final tool
    caches the whole tool block. Order must stay deterministic — a reordered
    tool list is a different prefix and silently costs a full re-read.
    """
    if not tools:
        return []
    out = [dict(t) for t in tools]
    out[-1]["cache_control"] = {"type": "ephemeral"}
    return out


class AnthropicLLM:
    """Production backend."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        max_tokens: int = 8192,
        timeout: float = 120.0,
        thinking: bool = True,
    ) -> None:
        if anthropic is None:
            raise AnthropicError("anthropic SDK not installed: pip install anthropic")
        key = api_key or load_api_key()
        if not key:
            raise AnthropicError(
                "no ANTHROPIC_API_KEY in the environment or .env — see docs/SETUP.md"
            )
        self.model = model
        self.max_tokens = max_tokens
        self.thinking = thinking
        self._client = anthropic.Anthropic(api_key=key, timeout=timeout)
        self.calls: list[dict[str, Any]] = []
        self.usage: dict[str, int] = {"input": 0, "output": 0,
                                      "cache_read": 0, "cache_write": 0}

    def available(self) -> bool:
        try:
            self._client.models.retrieve(self.model)
        except Exception:
            return False
        return True

    # -- request shaping --------------------------------------------------

    def _kwargs(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            # The caller passes a role-specific model id; this backend is
            # configured with one model, so ignore it and stay consistent.
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": messages,
        }
        if system:
            # A cache breakpoint here covers the rulebook and house style,
            # which never change between calls.
            kwargs["system"] = [{
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }]
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        return kwargs

    def _record_usage(self, usage: Any) -> dict[str, int]:
        counts = {
            "input": getattr(usage, "input_tokens", 0) or 0,
            "output": getattr(usage, "output_tokens", 0) or 0,
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }
        for key, value in counts.items():
            self.usage[key] += value
        return counts

    # -- LLM protocol -----------------------------------------------------

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        try:
            response = self._client.messages.create(
                **self._kwargs(system, messages, tools)
            )
        except anthropic.RateLimitError as exc:
            raise AnthropicError(f"rate limited: {exc}") from None
        except anthropic.AuthenticationError:
            raise AnthropicError("ANTHROPIC_API_KEY was rejected") from None
        except anthropic.APIStatusError as exc:
            raise AnthropicError(f"Anthropic returned {exc.status_code}: "
                                 f"{exc.message}") from None
        except anthropic.APIConnectionError as exc:
            raise AnthropicError(f"cannot reach Anthropic ({exc})") from None

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                # Arguments arrive already parsed here, unlike the
                # OpenAI-compatible backends where they are a JSON string.
                calls.append(ToolCall(id=block.id, name=block.name,
                                      args=dict(block.input or {})))
            # `thinking` blocks are not narrated: reasoning is not an answer,
            # and its provisional numbers would fail the verifier.

        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=calls,
            stop_reason=response.stop_reason or "end_turn",
            usage=self._record_usage(response.usage),
        )

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> Iterator[StreamEvent]:
        with self._client.messages.stream(
            **self._kwargs(system, messages, tools)
        ) as stream:
            for text in stream.text_stream:
                yield StreamEvent("token", {"text": text})
            final = stream.get_final_message()

        for block in final.content:
            if block.type == "tool_use":
                yield StreamEvent("tool_call",
                                  {"tool": block.name, "args": dict(block.input or {})})
        self._record_usage(final.usage)
        yield StreamEvent("done", {"stop_reason": final.stop_reason or "end_turn"})

    def cache_report(self) -> str:
        """Human-readable cache effectiveness, for the console status bar."""
        read, write = self.usage["cache_read"], self.usage["cache_write"]
        total = read + write + self.usage["input"]
        if not total:
            return "no calls yet"
        return (f"{read:,} cached / {total:,} input tokens "
                f"({100 * read // total}% served from cache)")
