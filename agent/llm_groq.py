"""Groq client — hosted inference over the OpenAI-compatible API.

Satisfies `agent.llm.LLM`, so switching from the local model is a config
change and nothing else moves.

Two shape differences from Ollama, both handled here:

  * `tool_calls[].function.arguments` arrives as a **JSON string**, not an
    object. `_coerce_args` already parses strings, so the same repair logic
    covers both backends.
  * Reasoning models return a `reasoning` field alongside `content`. It is
    kept out of the narrative — it is the model thinking aloud, not an answer,
    and the verifier would rightly reject the unsourced numbers in it.

The key comes from `GROQ_API_KEY` in the environment or a gitignored `.env`.
It is never logged, and never written into a trace or a response.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from agent.llm import LLMResponse, StreamEvent, ToolCall
from agent.llm_ollama import _coerce_args, _schema_for, _to_ollama_tools

BASE_URL = "https://api.groq.com/openai/v1"
# Cloudflare in front of Groq rejects the default `Python-urllib/3.x` agent
# with a 403 (error 1010). Any conventional agent string is accepted.
USER_AGENT = "dcortex-crew-advisor/0.1"
DEFAULT_MODEL = "qwen/qwen3.6-27b"
REPO_ROOT = Path(__file__).resolve().parent.parent


THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.S | re.I)


def strip_reasoning(text: str) -> str:
    """Remove any <think> block the model emitted into its content.

    Belt and braces alongside `reasoning_format=hidden`: a model that leaks
    its chain of thought would otherwise have that shipped to a controller as
    the answer.
    """
    return THINK_RE.sub("", text or "").strip()


class GroqError(RuntimeError):
    pass


def load_api_key() -> str | None:
    """`GROQ_API_KEY` from the environment, else from a local .env."""
    if key := os.environ.get("GROQ_API_KEY"):
        return key
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("GROQ_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


class GroqLLM:
    """Hosted backend. Same protocol as the local one, an order faster."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        timeout: int = 120,
        temperature: float = 0.0,
        base_url: str = BASE_URL,
        max_retries: int = 4,
        hide_reasoning: bool = True,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self.max_retries = max_retries
        self.hide_reasoning = hide_reasoning
        self._key = api_key or load_api_key()
        self.calls: list[dict[str, Any]] = []

    def available(self) -> bool:
        """Whether the key works and this model is in the catalogue."""
        if not self._key:
            return False
        try:
            request = urllib.request.Request(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self._key}",
                         "User-Agent": USER_AGENT},
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                ids = {m["id"] for m in json.loads(response.read()).get("data", [])}
        except Exception:
            return False
        return self.model in ids

    # -- transport --------------------------------------------------------

    def _post(self, payload: dict[str, Any], stream: bool = False) -> Any:
        if not self._key:
            raise GroqError(
                "no GROQ_API_KEY in the environment or .env — see docs/SETUP.md"
            )
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        for attempt in range(self.max_retries + 1):
            try:
                response = urllib.request.urlopen(request, timeout=self.timeout)
                return response if stream else json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                # 429 is expected on the free tier: the input-token allowance is
                # 7,000/minute and one tier-2 question with the enriched tool
                # schema runs ~2,400, so three questions exhaust it. Groq names
                # the wait in the error; honour it rather than guessing.
                if exc.code == 429 and attempt < self.max_retries:
                    time.sleep(min(self._retry_after(detail), 30.0))
                    continue
                if exc.code == 429:
                    raise GroqError(
                        "Groq rate limit exhausted after "
                        f"{self.max_retries} retries. The free tier allows 7,000 "
                        "input tokens/minute; wait a moment or upgrade the tier."
                    ) from None
                # Never echo the key, even in an error path.
                raise GroqError(f"Groq returned {exc.code}: {detail}") from None
            except urllib.error.URLError as exc:
                raise GroqError(f"cannot reach Groq ({exc.reason})") from None
        raise GroqError("unreachable")

    @staticmethod
    def _retry_after(detail: str) -> float:
        """Seconds Groq asked us to wait, from its own message."""
        match = re.search(r"try again in ([\d.]+)s", detail)
        return float(match.group(1)) + 0.5 if match else 5.0

    def _body(self, system: str, messages: list[dict[str, Any]],
              tools: list[dict[str, Any]] | None, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            # The caller names an Anthropic model id; ignore it so the same
            # advisor code drives every backend unchanged.
            "model": self.model,
            "temperature": self.temperature,
            "stream": stream,
            "messages": ([{"role": "system", "content": system}] if system else [])
                        + [self._flatten(m) for m in messages],
        }
        if tools:
            body["tools"] = _to_ollama_tools(tools)   # already OpenAI shape
            body["tool_choice"] = "auto"
        if self.hide_reasoning:
            # Without this qwen3.6 returns its entire chain of thought as the
            # message content, and that reasoning becomes the answer the
            # controller reads. It also slips past the verifier, because the
            # model is reciting figures from the prompt it was given — sourced,
            # but not an answer.
            body["reasoning_format"] = "hidden"
        return body

    @staticmethod
    def _flatten(message: dict[str, Any]) -> dict[str, Any]:
        """Collapse Anthropic-shaped content blocks into plain text.

        The advisor builds tool_use/tool_result blocks; this API wants strings,
        so flatten rather than fork the loop.
        """
        content = message.get("content")
        if isinstance(content, str):
            return {"role": message["role"], "content": content}

        parts: list[str] = []
        for block in content or []:
            if not isinstance(block, dict):
                parts.append(str(block))
            elif block.get("type") == "tool_use":
                parts.append(f"[called {block.get('name')} "
                             f"with {json.dumps(block.get('input', {}))}]")
            elif block.get("type") == "tool_result":
                parts.append(f"[result] {block.get('content')}")
            else:
                parts.append(block.get("text", ""))
        return {"role": message["role"], "content": "\n".join(parts)}

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
        data = self._post(self._body(system, messages, tools, stream=False))

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        calls: list[ToolCall] = []
        for i, raw in enumerate(message.get("tool_calls") or []):
            fn = raw.get("function") or {}
            name = fn.get("name") or ""
            calls.append(ToolCall(
                id=raw.get("id") or f"groq-{i}",
                name=name,
                # `arguments` is a JSON string here, not an object.
                args=_coerce_args(fn.get("arguments"), _schema_for(tools, name)),
            ))

        usage = data.get("usage") or {}
        return LLMResponse(
            # `reasoning` is deliberately dropped: it is the model thinking
            # aloud, full of provisional numbers the verifier would reject.
            text=strip_reasoning(message.get("content") or ""),
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            usage={"input": usage.get("prompt_tokens", 0),
                   "output": usage.get("completion_tokens", 0)},
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
        response = self._post(self._body(system, messages, tools, stream=True),
                              stream=True)
        pending: dict[int, dict[str, Any]] = {}

        with response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    continue

                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}

                # Tool calls arrive fragmented across chunks; accumulate the
                # argument string until the stream closes.
                for part in delta.get("tool_calls") or []:
                    slot = pending.setdefault(part.get("index", 0),
                                              {"name": "", "args": ""})
                    fn = part.get("function") or {}
                    slot["name"] += fn.get("name") or ""
                    slot["args"] += fn.get("arguments") or ""

                if text := delta.get("content"):
                    yield StreamEvent("token", {"text": text})

        for slot in pending.values():
            yield StreamEvent("tool_call", {
                "tool": slot["name"],
                "args": _coerce_args(slot["args"], _schema_for(tools, slot["name"])),
            })
        yield StreamEvent("done", {"stop_reason": "stop"})
