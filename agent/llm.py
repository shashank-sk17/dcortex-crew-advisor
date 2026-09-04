"""The LLM port — the single place the outside world gets called.

Nothing in this package makes a network request today. `PlaceholderLLM` returns
deterministic canned responses so the whole pipeline runs, and every test in
`agent/tests/` passes, with no API key and no SDK installed.

Swapping in the real client means implementing `AnthropicLLM` below. Nothing
else in the package changes, because everything depends on the `LLM` protocol
rather than on a vendor SDK.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Protocol, runtime_checkable

from agent import config

# --------------------------------------------------------------------------
# Wire types (vendor-neutral)
# --------------------------------------------------------------------------


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LLMResponse:
    """One turn. Either the model wants tools, or it produced final text."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass(slots=True)
class StreamEvent:
    """Matches the SSE contract in docs/API_CONTRACT.md."""

    event: str  # "token" | "tool_call" | "tool_result" | "done"
    data: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLM(Protocol):
    """What the agent needs from a language model. Deliberately small."""

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse: ...

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> Iterator[StreamEvent]: ...


# --------------------------------------------------------------------------
# Placeholder implementation
# --------------------------------------------------------------------------


class PlaceholderLLM:
    """Deterministic stand-in. No network, no key, no SDK.

    It is not pretending to be smart. It exists so the surrounding machinery —
    routing, the tool loop, the verifier, streaming — is exercisable and
    testable today. Scripted replies can be queued for specific tests.

    >>> llm = PlaceholderLLM()
    >>> llm.complete(system="", messages=[{"role": "user", "content": "hi"}]).text
    '[placeholder] no model configured; see agent/llm.py'
    """

    DEFAULT_TEXT = "[placeholder] no model configured; see agent/llm.py"

    def __init__(self, scripted: list[LLMResponse] | None = None) -> None:
        self._scripted = list(scripted or [])
        self.calls: list[dict[str, Any]] = []

    def _record(self, **kw: Any) -> None:
        self.calls.append(kw)

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        self._record(system=system, messages=messages, tools=tools, model=model)
        if self._scripted:
            return self._scripted.pop(0)
        return LLMResponse(text=self.DEFAULT_TEXT, usage={"input": 0, "output": 0})

    def stream(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
    ) -> Iterator[StreamEvent]:
        response = self.complete(
            system=system, messages=messages, tools=tools,
            model=model, max_tokens=max_tokens,
        )
        for call in response.tool_calls:
            yield StreamEvent("tool_call", {"tool": call.name, "args": call.args})
        for word in response.text.split():
            yield StreamEvent("token", {"text": word + " "})
        yield StreamEvent("done", {"stop_reason": response.stop_reason})


class ScriptedRouterLLM(PlaceholderLLM):
    """Placeholder that answers routing prompts with a fixed intent.

    The router falls back to an LLM only when its deterministic rules abstain,
    so tests need a way to drive that branch without a real model.
    """

    def __init__(self, intent: str, confidence: str = "medium") -> None:
        super().__init__()
        self._payload = json.dumps({"intent": intent, "confidence": confidence})

    def complete(self, **kw: Any) -> LLMResponse:  # type: ignore[override]
        self._record(**kw)
        return LLMResponse(text=self._payload)


# --------------------------------------------------------------------------
# Real client — not implemented yet, deliberately
# --------------------------------------------------------------------------


class AnthropicLLM:
    """Real client. **Not implemented — placeholder only.**

    To land this (issue #24), implement `complete` and `stream` against the
    Messages API and keep the return types above unchanged:

      * models come from `agent.config` (ROUTER_MODEL / ADVISOR_MODEL /
        EXPLAINER_MODEL) — do not hardcode ids here;
      * mark the system prompt and the tool definitions as cache breakpoints;
        they are long, static, and hit on every single turn;
      * map the vendor's tool-use blocks onto `ToolCall`, and its streaming
        deltas onto `StreamEvent` so `api/` needs no changes;
      * `stop_reason == "tool_use"` must set `LLMResponse.stop_reason`, because
        `agent.advisor` loops on it.

    Confirm parameter names against the current SDK before writing this; do not
    reconstruct them from memory.
    """

    def __init__(self, *_: Any, **__: Any) -> None:
        raise NotImplementedError(
            "AnthropicLLM is a placeholder. Use PlaceholderLLM, or implement "
            "this against the Messages API — see the class docstring."
        )


def default_llm() -> LLM:
    """What the rest of the package uses when no client is injected."""
    return PlaceholderLLM()


__all__ = [
    "LLM",
    "LLMResponse",
    "ToolCall",
    "StreamEvent",
    "PlaceholderLLM",
    "ScriptedRouterLLM",
    "AnthropicLLM",
    "default_llm",
    "config",
]
