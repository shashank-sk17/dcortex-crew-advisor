"""Argument repair for local models.

Every malformation here was produced by a real model against this repo's tool
schemas. The repairs exist because small models mangle structured arguments,
not as defensive paranoia.
"""

from __future__ import annotations

from agent.llm_ollama import OllamaLLM, _coerce_args

SCHEMA = {
    "type": "object",
    "properties": {"entity": {"type": "string"}, "filters": {"type": "object"}},
    "required": ["entity"],
}


class TestCoerceArgs:
    def test_clean_arguments_pass_through(self):
        assert _coerce_args({"entity": "reserves"}, SCHEMA) == {"entity": "reserves"}

    def test_arguments_delivered_as_a_json_string(self):
        assert _coerce_args('{"entity": "crew"}', SCHEMA) == {"entity": "crew"}

    def test_everything_stuffed_into_one_property(self):
        """llama3.2:3b: the whole object nested inside `filters` as a string."""
        raw = {"filters": '{"entity": "reserves", "filters": {"base": "BLR"}}', "object": None}
        assert _coerce_args(raw, SCHEMA) == {"entity": "reserves", "filters": {"base": "BLR"}}

    def test_truncated_json_is_repaired(self):
        """Models routinely drop the closing brace."""
        raw = {"filters": '{"entity": "reserves", "filters": {"base": "BLR"}'}
        assert _coerce_args(raw, SCHEMA)["entity"] == "reserves"

    def test_invented_keys_dropped(self):
        assert _coerce_args({"entity": "crew", "object": None, "junk": 1}, SCHEMA) == {"entity": "crew"}

    def test_nested_object_unwrapped(self):
        assert _coerce_args({"arguments": {"entity": "flights"}}, SCHEMA) == {"entity": "flights"}

    def test_json_string_coerced_to_object(self):
        got = _coerce_args({"entity": "crew", "filters": '{"base": "DEL"}'}, SCHEMA)
        assert got["filters"] == {"base": "DEL"}

    def test_missing_required_yields_nothing(self):
        """Unusable beats wrong — the caller falls back to a seeded call."""
        assert _coerce_args({"filters": {"base": "BLR"}}, SCHEMA) == {}

    def test_string_null_dropped(self):
        """llama3.2 emits the string "null" for an absent optional argument.
        Left alone it reaches duty_clock as a literal date of "null"."""
        schema = {"type": "object",
                  "properties": {"crew_id": {"type": "string"}, "date": {"type": "string"}},
                  "required": ["crew_id"]}
        got = _coerce_args({"crew_id": "C-1042", "date": "null"}, schema)
        assert got == {"crew_id": "C-1042"}

    def test_garbage_yields_nothing(self):
        assert _coerce_args("not json at all", SCHEMA) == {}
        assert _coerce_args(None, SCHEMA) == {}


class TestMessageFlattening:
    def test_tool_blocks_become_text(self):
        msg = {"role": "assistant", "content": [
            {"type": "tool_use", "name": "lookup", "input": {"entity": "crew"}}]}
        assert "lookup" in OllamaLLM._flatten(msg)["content"]

    def test_plain_string_untouched(self):
        assert OllamaLLM._flatten({"role": "user", "content": "hi"})["content"] == "hi"


class TestGroqReasoningLeak:
    """qwen3.6 returned its entire chain of thought as the message content, and
    that reasoning became the answer a controller would read.

    Worse, it verified clean — the model was reciting figures from the prompt
    it had been handed, so every number was technically sourced. The gate
    cannot catch this; not shipping reasoning is the fix.
    """

    def test_think_block_removed(self):
        from agent.llm_groq import strip_reasoning

        got = strip_reasoning("<think>step one\nstep two</think>Use C-3310.")
        assert got == "Use C-3310."

    def test_unterminated_think_block_removed(self):
        """Truncation mid-thought must not leak the whole draft."""
        from agent.llm_groq import strip_reasoning

        assert strip_reasoning("<think>reasoning that never closes") == ""

    def test_plain_text_untouched(self):
        from agent.llm_groq import strip_reasoning

        assert strip_reasoning("Use C-3310 — ₹18,500.") == "Use C-3310 — ₹18,500."

    def test_reasoning_hidden_at_the_source(self):
        from agent.llm_groq import GroqLLM

        body = GroqLLM(api_key="x")._body("sys", [{"role": "user", "content": "hi"}],
                                          None, stream=False)
        assert body["reasoning_format"] == "hidden"

    def test_arguments_arrive_as_a_json_string(self):
        """Groq sends OpenAI-shaped arguments: a string, not an object."""
        from agent.llm_ollama import _coerce_args

        schema = {"type": "object", "properties": {"entity": {"type": "string"}},
                  "required": ["entity"]}
        assert _coerce_args('{"entity":"reserves"}', schema) == {"entity": "reserves"}
