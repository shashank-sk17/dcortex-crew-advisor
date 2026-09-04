"""Ollama client — local Llama for development.

Satisfies `agent.llm.LLM`, so swapping to a hosted API later touches this file
and `agent.config` and nothing else.

**Small local models are unreliable at tool calling.** Measured on this repo at
temperature 0: `llama3` (8B) has no tool support at all and returns empty;
`llama3.2` (3B) emits a malformed blob into `content` and confuses the tool
description for its name; `llama3.1:8b` calls tools but still produces
arguments that need repair.

That is survivable here only because the architecture never depended on the
model to decide: `agent.router` is deterministic (38/38 on the gold set with no
model at all) and `agent.advisor.seed_calls` fills arguments from regex-
extracted entities. Locally the model is a narrator. Expect tool *selection* to
improve materially on a hosted model — not just get faster.

`_coerce_args` below repairs the specific malformations observed rather than
trusting the model's JSON.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator

from agent.llm import LLMResponse, StreamEvent, ToolCall

DEFAULT_HOST = "http://localhost:11434"

# Measured on this repo's tool schemas, temperature 0, three tier-1 questions:
#
#   llama3.1:8b   3/3 usable tool calls
#   llama3.2      2/3 — misses the reserve lookup entirely, emits "null" dates
#   llama3        0/3 — no tool support at all in the original Llama 3
#
# `llama3.2` is newer than `llama3.1` but far smaller: the Ollama tag is the 3B
# text model, against 8B for llama3.1:8b. Newer version, fewer parameters.
DEFAULT_MODEL = "llama3.2"
BEST_TESTED_MODEL = "llama3.1:8b"


class OllamaError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Argument repair
# --------------------------------------------------------------------------


def _schema_for(tools: list[dict[str, Any]] | None, name: str) -> dict[str, Any]:
    for tool in tools or []:
        if tool.get("name") == name:
            return tool.get("input_schema") or {}
    return {}


def _coerce_args(raw: Any, schema: dict[str, Any]) -> dict[str, Any]:
    """Salvage a usable argument dict from whatever the model produced.

    Handles, in order, the failures actually seen from local Llama models:
      * arguments delivered as a JSON string rather than an object
      * every argument stuffed into one property as a JSON string
      * invented keys (`{"object": null}`) that are not in the schema
      * a value that is itself the whole argument object
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}

    props: dict[str, Any] = schema.get("properties") or {}
    required: list[str] = schema.get("required") or []

    # A single property holding a JSON string of the real arguments.
    for key, value in list(raw.items()):
        if isinstance(value, str) and value.lstrip().startswith("{"):
            try:
                inner = json.loads(value)
            except json.JSONDecodeError:
                # Models truncate these; a trailing brace often repairs them.
                try:
                    inner = json.loads(value + "}")
                except json.JSONDecodeError:
                    continue
            if isinstance(inner, dict) and any(k in props for k in inner):
                raw = {**{k: v for k, v in raw.items() if k != key}, **inner}

    # A nested object that is really the whole argument set.
    if props and not any(k in props for k in raw):
        for value in raw.values():
            if isinstance(value, dict) and any(k in props for k in value):
                raw = value
                break

    cleaned = {k: v for k, v in raw.items() if k in props} if props else dict(raw)

    # Models emit the *string* "null" for an absent optional argument.
    # Left alone it becomes a literal date of "null" downstream.
    cleaned = {
        k: v for k, v in cleaned.items()
        if not (isinstance(v, str) and v.strip().lower() in {"null", "none", "undefined", ""})
    }

    # Coerce a JSON string into the object/array the schema asks for.
    for key, value in list(cleaned.items()):
        want = (props.get(key) or {}).get("type")
        if want in ("object", "array") and isinstance(value, str):
            try:
                cleaned[key] = json.loads(value)
            except json.JSONDecodeError:
                cleaned.pop(key)
        elif want == "number" and isinstance(value, str):
            try:
                cleaned[key] = float(value)
            except ValueError:
                cleaned.pop(key)

    if any(r not in cleaned for r in required):
        return {}  # unusable; the caller falls back to a seeded call
    return cleaned


def _to_ollama_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools or []
    ]


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class OllamaLLM:
    """Local Ollama backend.

    Requires a running daemon (`ollama serve`); `available()` reports whether
    the daemon is up and the model pulled, so callers can fall back without
    raising.
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        timeout: int = 180,
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.temperature = temperature
        self.calls: list[dict[str, Any]] = []

    # -- transport --------------------------------------------------------

    def _post(self, path: str, payload: dict[str, Any], stream: bool = False) -> Any:
        request = urllib.request.Request(
            f"{self.host}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.URLError as exc:
            raise OllamaError(
                f"cannot reach Ollama at {self.host} ({exc.reason}). "
                "Start it with `ollama serve`."
            ) from exc
        return response if stream else json.loads(response.read())

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as r:
                names = {m["name"] for m in json.loads(r.read()).get("models", [])}
        except Exception:
            return False
        return self.model in names or f"{self.model}:latest" in names

    def _body(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            # `model` from the caller names an Anthropic id; ignore it locally
            # so the same advisor code drives both backends unchanged.
            "model": self.model,
            "stream": stream,
            "options": {"temperature": self.temperature},
            "messages": (
                [{"role": "system", "content": system}] if system else []
            ) + [self._flatten(m) for m in messages],
        }
        if tools:
            body["tools"] = _to_ollama_tools(tools)
        return body

    @staticmethod
    def _flatten(message: dict[str, Any]) -> dict[str, Any]:
        """Collapse structured content blocks into text.

        The advisor builds Anthropic-shaped tool_use/tool_result blocks; Ollama
        wants plain strings, so flatten rather than diverge the loop.
        """
        content = message.get("content")
        if isinstance(content, str):
            return {"role": message["role"], "content": content}

        parts: list[str] = []
        for block in content or []:
            if not isinstance(block, dict):
                parts.append(str(block))
            elif block.get("type") == "tool_use":
                parts.append(f"[called {block.get('name')} with {json.dumps(block.get('input', {}))}]")
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
        data = self._post("/api/chat", self._body(system, messages, tools, model, False))

        message = data.get("message") or {}
        calls: list[ToolCall] = []
        for i, raw in enumerate(message.get("tool_calls") or []):
            fn = raw.get("function") or {}
            name = fn.get("name") or ""
            args = _coerce_args(fn.get("arguments"), _schema_for(tools, name))
            calls.append(ToolCall(id=raw.get("id") or f"ollama-{i}", name=name, args=args))

        return LLMResponse(
            text=message.get("content") or "",
            tool_calls=calls,
            stop_reason="tool_use" if calls else "end_turn",
            usage={
                "input": data.get("prompt_eval_count", 0),
                "output": data.get("eval_count", 0),
            },
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
        response = self._post(
            "/api/chat", self._body(system, messages, tools, model, True), stream=True
        )
        with response:
            for line in response:
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue

                message = chunk.get("message") or {}
                for raw in message.get("tool_calls") or []:
                    fn = raw.get("function") or {}
                    name = fn.get("name") or ""
                    yield StreamEvent("tool_call", {
                        "tool": name,
                        "args": _coerce_args(fn.get("arguments"), _schema_for(tools, name)),
                    })
                if text := message.get("content"):
                    yield StreamEvent("token", {"text": text})
                if chunk.get("done"):
                    yield StreamEvent("done", {"stop_reason": chunk.get("done_reason", "stop")})
