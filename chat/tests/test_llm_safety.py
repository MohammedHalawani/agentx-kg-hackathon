"""Offline final-content contract tests: no provider or database calls."""
import importlib.util
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from llm.pipeline import _llm, graph
from llm import agent, translate


class FinalContentTests(unittest.TestCase):
    def test_serialized_harmony_real_tokens_and_named_aliases_are_final_only(self):
        for start, channel, message, end, finish in (
            ("<|im_start|>", "<|meta_sep|>", "<|im_sep|>", "<|im_end|>", "<|fim_suffix|>"),
            ("<|start|>", "<|channel|>", "<|message|>", "<|end|>", "<|return|>"),
            ("[im_start]", "[meta_sep]", "[im_sep]", "[im_end]", "[fim_suffix]"),
        ):
            transcript = (f"{start}assistant{channel}analysis{message}PRIVATE{end}"
                          f"{start}assistant{channel}final{message}تم تحديد السبب{finish}")
            self.assertEqual(_llm.message_text(transcript), "تم تحديد السبب")
            self.assertEqual(_llm.message_text(f"{channel}analysis{message}PRIVATE"), "")
            self.assertEqual(_llm.message_text(f"{start}assistant{channel}analysis"), "")
            self.assertEqual(_llm.message_text(f"{channel}final{message}{{\"category\":\"hub_delay\"}}{finish}"),
                             '{"category":"hub_delay"}')

    def test_serialized_harmony_does_not_forward_other_roles_or_later_analysis(self):
        prefix = "<|start|>assistant<|channel|>final<|message|>Safe"
        for suffix in (
            "<|end|><|start|>assistant<|channel|>analysis<|message|>PRIVATE<|end|>",
            "<|start|>assistant<|channel|>analysis<|message|>PRIVATE<|end|>",
        ):
            self.assertEqual(_llm.message_text(prefix + suffix), "Safe")
        for role in ("user", "tool", "assistant to=tool"):
            self.assertEqual(_llm.message_text(
                f"<|start|>{role}<|channel|>final<|message|>PRIVATE<|end|>"), "")
        self.assertEqual(_llm.message_text(
            "<|start|>assistant<|channel|>commentary<|message|>PRIVATE<|call|>"), "")
        structured = '<|start|>assistant<|channel|>final<|constrain|>json<|message|>{"category":"hub_delay"}<|return|>'
        self.assertEqual(_llm.parse_json(structured), {"category": "hub_delay"})
        with patch.object(_llm, "model") as factory:
            factory.return_value.invoke.return_value = AIMessage(content=structured)
            self.assertEqual(_llm.ask_json("System", "Complaint", {"category": "unknown"}),
                             {"category": "hub_delay"})

    def test_supported_final_shapes(self):
        for content in (
            "تم تحديد السبب SHP-0227",
            [{"type": "text", "text": "تم تحديد السبب SHP-0227"}],
            [{"type": "output_text", "text": "تم تحديد السبب SHP-0227"}],
            {"type": "text", "text": {"value": "تم تحديد السبب SHP-0227"}},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "تم تحديد السبب SHP-0227"}]},
            {"text": "تم تحديد السبب SHP-0227"},
            ["تم تحديد السبب ", "SHP-0227"],
        ):
            with self.subTest(content=content):
                self.assertEqual(_llm.message_text(content), "تم تحديد السبب SHP-0227")

    def test_private_blocks_ignored_even_with_text_key(self):
        blocks = [{"type": kind, "text": "PRIVATE", "thinking": "PRIVATE"}
                  for kind in ("thinking", "reasoning", "analysis", "redacted_thinking")]
        blocks += [{"type": "text", "channel": "analysis", "text": "PRIVATE"},
                   {"type": "text", "text": "Final answer"}]
        self.assertEqual(_llm.message_text(blocks), "Final answer")

    def test_missing_unknown_or_only_reasoning_content_is_empty(self):
        for content in (None, "", [], {}, 42, [{"type": "reasoning", "text": "PRIVATE"}],
                        {"type": "image", "text": "PRIVATE"},
                        {"type": {"reasoning": "PRIVATE"}, "text": "PRIVATE"},
                        {"type": "text", "channel": ["analysis"], "text": "PRIVATE"},
                        {"type": "message", "role": "user", "content": "PRIVATE"}):
            with self.subTest(content=content):
                self.assertEqual(_llm.message_text(content), "")

    def test_tagged_and_labeled_private_prose(self):
        for content in (
            "<think>PRIVATE</think>Final answer",
            "<THINKING>PRIVATE</THINKING>Final answer",
            "<reasoning mode='private'>PRIVATE</reasoning>Final answer",
            "<analysis>PRIVATE</analysis>Final answer",
            "PRIVATE</think>Final answer",
            "Analysis: PRIVATE\nFinal: Final answer",
            "Thinking: PRIVATE\nAnswer: Final answer",
            "[im_start]assistant[meta_sep]analysis[im_sep]PRIVATE[im_end]"
            "[im_start]assistant[meta_sep]final[im_sep]Final answer[fim_suffix]",
        ):
            with self.subTest(content=content):
                self.assertEqual(_llm.message_text(content), "Final answer")
        for content in ("<think>PRIVATE", "Analysis: PRIVATE", "[meta_sep]analysis[im_sep]PRIVATE"):
            self.assertEqual(_llm.message_text(content), "")

    def test_block_fragments_with_split_private_tags(self):
        self.assertEqual(_llm.message_text(["<thi", "nk>PRIVATE</thi", "nk>Final answer"]), "Final answer")

    def test_dict_json_only(self):
        for raw in ('[]', '[{"x": 1}]', 'null', '"answer"', '42', ''):
            self.assertIsNone(_llm.parse_json(raw))
        for raw in ('{"x": "السبب"}', '```json\n{"x": "السبب"}\n```',
                    'Preamble {"x": "السبب"} trailing prose',
                    '<think>{"x": "PRIVATE"}</think>{"x": "السبب"}'):
            self.assertEqual(_llm.parse_json(raw), {"x": "السبب"})
        self.assertEqual(_llm.parse_json('preamble {"x": "brace } and escaped \\\" quote"}'),
                         {"x": 'brace } and escaped " quote'})

    def test_ask_json_final_blocks_and_application_fields_only(self):
        content = [{"type": "thinking", "text": '{"rationale": "PRIVATE"}'},
                   {"type": "text", "text": json.dumps({"rationale": "الدليل النهائي", "confidence": 0.7,
                                                           "reasoning": "PRIVATE", "content": [{"type": "thinking"}]})}]
        mock = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content=content))
        with patch.object(_llm, "model", return_value=mock):
            self.assertEqual(_llm.ask_json("s", "u", {"rationale": "fallback", "confidence": 0.0}),
                             {"rationale": "الدليل النهائي", "confidence": 0.7})

    def test_ask_json_rejects_nested_provider_blocks_in_declared_fields(self):
        content = json.dumps({"rationale": [{"type": "thinking", "text": "PRIVATE"}],
                              "grounded_in": [{"reasoning": "PRIVATE"}, "res-1"],
                              "confidence": "PRIVATE", "city": {"reasoning": "PRIVATE"}})
        mock = SimpleNamespace(invoke=lambda messages: SimpleNamespace(content=content))
        default = {"rationale": "fallback", "grounded_in": [], "confidence": 0.0, "city": None}
        with patch.object(_llm, "model", return_value=mock):
            self.assertEqual(_llm.ask_json("s", "u", default),
                             {"rationale": "fallback", "grounded_in": ["res-1"], "confidence": 0.0, "city": None})

    def test_ask_json_sanitizes_marked_final_fields(self):
        mock = SimpleNamespace(invoke=lambda messages: SimpleNamespace(
            content='{"rationale": "<think>PRIVATE</think>Evidence"}'))
        with patch.object(_llm, "model", return_value=mock):
            self.assertEqual(_llm.ask_json("s", "u", {"rationale": "fallback"}), {"rationale": "Evidence"})

    def test_missing_content_and_invalid_json_fallback_without_raw_log(self):
        for response in (SimpleNamespace(), SimpleNamespace(content="PRIVATE invalid JSON"),
                         SimpleNamespace(content="[]")):
            with patch.object(_llm, "model", return_value=SimpleNamespace(invoke=lambda messages: response)):
                with self.assertLogs(_llm.log, level=logging.WARNING) as captured:
                    actual = _llm.ask_json("s", "u", {"items": []})
                self.assertEqual(actual, {"items": []})
                self.assertNotIn("PRIVATE", "".join(captured.output))

    def test_translation_never_stringifies_reasoning_blocks(self):
        translate.to_arabic.cache_clear()
        content = [{"type": "reasoning", "text": "PRIVATE We need to translate"},
                   {"type": "text", "text": "تأخر تسليم الشحنة SHP-0227"}]
        with patch.object(translate, "model", return_value=SimpleNamespace(invoke=lambda messages: SimpleNamespace(content=content))):
            self.assertEqual(translate.to_arabic("Shipment SHP-0227 is delayed"), "تأخر تسليم الشحنة SHP-0227")

    def test_translation_only_reasoning_falls_back_to_source(self):
        translate.to_arabic.cache_clear()
        content = [{"type": "thinking", "text": "PRIVATE العربية"}]
        with patch.object(translate, "model", return_value=SimpleNamespace(invoke=lambda messages: SimpleNamespace(content=content))):
            self.assertEqual(translate.to_arabic("Shipment SHP-9999"), "Shipment SHP-9999")

    def test_stream_dto_drops_extra_and_nested_private_fields(self):
        out = graph._summarize("recommend", {"recommendation": {
            "action": "contact_recipient", "rationale": "<think>PRIVATE</think>Evidence",
            "reasoning": "PRIVATE", "content": [{"type": "thinking", "text": "PRIVATE"}],
            "grounded_in": ["res-1", {"reasoning": "PRIVATE"}],
            "grounded_cases": [{"resolution_id": "res-1", "thinking": "PRIVATE"}],
            "candidates": [{"action": "contact_recipient", "rate": 0.8, "reasoning": "PRIVATE"}],
        }}, 0)
        self.assertNotIn("PRIVATE", json.dumps(out))
        self.assertIn("Operator approval", out["detail"]["rationale"])
        self.assertEqual(out["detail"]["grounded_in"], ["res-1"])

    def test_pipeline_final_dto_uses_same_allowlist(self):
        update = {"classification": {"category": "hub_delay", "rationale": "Evidence", "thinking": "PRIVATE"}}
        fake = SimpleNamespace(stream=lambda state, **kwargs: iter([{"classify": update}]))
        with patch.object(graph, "build_pipeline", return_value=fake):
            events = list(graph.stream_complaint("Complaint"))
        self.assertNotIn("PRIVATE", json.dumps(events))
        self.assertEqual(events[-1][1]["classification"]["category"], "hub_delay")

    def test_legacy_stream_outputs_completed_final_message_only(self):
        content = [{"type": "thinking", "thinking": "PRIVATE"}, {"type": "text", "text": "Final answer"}]
        final = {"messages": [HumanMessage("Question"), AIMessage(content=content, additional_kwargs={"reasoning_content": "PRIVATE"})]}
        modes = []
        def stream(state, **kwargs):
            modes.extend(kwargs["stream_mode"])
            yield "values", final
        with patch.object(agent, "_agent", return_value=SimpleNamespace(stream=stream)):
            events = list(agent.stream_agent("Question"))
        self.assertEqual(modes, ["updates", "values"])
        self.assertEqual(events[0], ("token", "Final answer"))
        self.assertNotIn("PRIVATE", json.dumps(events))

    def test_provider_config_is_forwarded_unchanged(self):
        _llm.model.cache_clear()
        with patch.object(_llm.config, "LLM_MODEL", "openai/gpt-oss:20b"), \
             patch.object(_llm.config, "LLM_API_BASE", "https://ollama.com/v1"), \
             patch.object(_llm.config, "LLM_API_KEY", "test-key"), patch.object(_llm, "ChatLiteLLM") as cls:
            _llm.model()
            cls.assert_called_once_with(model="openai/gpt-oss:20b", api_base="https://ollama.com/v1", api_key="test-key", temperature=0)
        _llm.model.cache_clear()


class ConfigTests(unittest.TestCase):
    def test_api_key_fallback_precedence_and_local_no_key(self):
        base = {"NEO4J_URI": "bolt://test.invalid:7687", "NEO4J_USERNAME": "test", "NEO4J_PASSWORD": "test"}
        for keys, expected in (
            ({"LLM_API_KEY": "explicit", "OPENAI_API_KEY": "openai", "OLLAMA_API_KEY": "ollama"}, "explicit"),
            ({"OPENAI_API_KEY": "openai", "OLLAMA_API_KEY": "ollama"}, "openai"),
            ({"OLLAMA_API_KEY": "ollama"}, "ollama"), ({}, None),
        ):
            spec = importlib.util.spec_from_file_location("test_config", Path(__file__).parents[1] / "config.py")
            cfg = importlib.util.module_from_spec(spec)
            with patch.dict(os.environ, {**base, **keys}, clear=True), patch("dotenv.load_dotenv"):
                spec.loader.exec_module(cfg)
            self.assertEqual(cfg.LLM_API_KEY, expected)
            self.assertEqual(cfg.LLM_MODEL, "openai/gpt-oss:120b")
            self.assertEqual(cfg.LLM_API_BASE, "https://ollama.com/v1")


class BackendStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).parents[2]))
        from backend import main
        cls.main = main

    def test_chat_does_not_forward_reasoning_events(self):
        self.main._answer_cache.clear()
        async def collect():
            return [event async for event in self.main._stream(self.main.ChatRequest(message="offline stream test"))]
        with patch.object(self.main, "stream_agent", return_value=iter([("reasoning", "PRIVATE"), ("token", "Final answer")])):
            events = asyncio.run(collect())
        self.assertNotIn("PRIVATE", "".join(events))
        self.assertIn("Final answer", "".join(events))
        self.main._answer_cache.clear()

    def test_complaint_does_not_forward_unknown_provider_events(self):
        async def collect():
            return [event async for event in self.main._stream_complaint("offline complaint")]
        with patch.object(self.main.pipeline_graph, "stream_complaint", return_value=iter([
            ("reasoning", {"text": "PRIVATE"}), ("provider_content", {"text": "PRIVATE"}),
            ("stage", {"stage": "classify", "detail": {"category": "hub_delay"}}),
        ])):
            events = asyncio.run(collect())
        self.assertNotIn("PRIVATE", "".join(events))
        self.assertIn("hub_delay", "".join(events))


if __name__ == "__main__":
    unittest.main()
