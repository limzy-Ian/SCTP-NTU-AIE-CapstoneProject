"""Phase 5c: no condition judgements for inference questions, dates written as "30 Jun 2026", Celsius by name."""
import json
import unittest
from unittest.mock import patch

from jm_rag import key_figures, validator
from jm_rag.guardrails import names
from jm_rag.pipeline import answer_question
from jm_rag.prompt import SYSTEM_PROMPT
from tests.fixtures import build_fixture_sources
from tests.mock_client import MockClient

QUESTION = "Is TST-01 in good shape?"


def machine_reply(text):
    def reply(kwargs):
        for message in reversed(kwargs["messages"]):
            if "Retrieved evidence:\n" in message["content"]:
                for source in json.loads(message["content"].split("Retrieved evidence:\n", 1)[1]):
                    if source["title"].startswith("TST-01 /"):
                        return text.replace("[M]", f"[{source['id']}]")
        raise AssertionError("no TST-01 source in the prompt")
    return reply


def ask(client, question=QUESTION):
    with patch.dict("os.environ", {}, clear=True):
        return answer_question(question, [], (build_fixture_sources(), []), client, model="m")


class PhraseTests(unittest.TestCase):
    def test_every_listed_phrase_is_found(self):
        for phrase in validator.CONDITION_JUDGEMENTS:
            with self.subTest(phrase=phrase):
                self.assertTrue(validator.condition_judgements(f"The pump is {phrase} today."))

    def test_negated_sentences_are_still_caught(self):
        for text in ("It cannot be concluded that the compressor is in good shape.",
                     "The data does not show that it is safe to run.", "I cannot say there are no problems."):
            with self.subTest(text=text):
                self.assertTrue(validator.condition_judgements(text))

    def test_legitimate_sentences_pass(self):
        for text in ("The records show 3 overheat trips; the data cannot judge the machine's condition.",
                     "Follow the SOP; the shape of the bracket is in the drawing.", "The crane has a safe working load of 2,000 kg.",
                     "Healthcare is not covered."):
            with self.subTest(text=text):
                self.assertEqual(validator.condition_judgements(text), [])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)

    def test_a_judgement_is_retried_with_the_reason_and_a_clean_retry_is_kept(self):
        client = MockClient([machine_reply("TST-01 is in good shape [M]."),
                             machine_reply("TST-01 is a lathe; the data cannot judge its condition [M].")])
        result = ask(client)
        self.assertEqual(len(client.calls), 2)
        retry = client.calls[1]["messages"][-1]["content"]
        self.assertIn('Do not use these phrases, not even in a negated sentence: "in good shape"', retry)
        self.assertIn("the data cannot judge its condition", result["answer"])
        self.assertEqual(result["outcome"], "abstain")
        self.assertEqual(result["usage"]["calls"], 2)

    def test_a_negated_judgement_twice_falls_back_to_the_template(self):
        client = MockClient([machine_reply("It cannot be concluded that TST-01 is in good shape [M].")] * 2)
        result = ask(client)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("no AI wording was generated", result["answer"])
        self.assertNotIn("in good shape", result["answer"].split("\n\nNotes:")[0])
        self.assertIn("model answer failed validation twice; template used", result["errors"])

    def test_the_check_only_applies_to_inference_questions(self):
        client = MockClient([machine_reply("TST-01 has no problems recorded in its nameplate fields [M].")])
        result = ask(client, "what is the serial number of TST-01")
        self.assertEqual(len(client.calls), 1)


class FormatTests(unittest.TestCase):
    def test_the_prompt_asks_for_dates_as_30_jun_2026(self):
        self.assertIn("30 Jun 2026, never as 2026-06-30", SYSTEM_PROMPT)

    def test_the_data_end_caveat_accepts_only_30_jun_2026(self):
        self.assertEqual(key_figures.DATA_END_OPTIONS, ["30 Jun 2026"])
        self.assertFalse(key_figures.stated("open as of 2026-06-30", key_figures.DATA_END_OPTIONS))
        self.assertTrue(key_figures.stated("open as of 30 Jun 2026", key_figures.DATA_END_OPTIONS))

    def test_the_celsius_caveat_needs_the_word(self):
        from jm_rag.facts import facts_source
        question = "Show the sensor data for TST-01 in degrees Fahrenheit."
        sources = [s for s in build_fixture_sources() if s["source_type"] != "sensor_trend_monthly"]
        sources.append({"title": "TST-01 / monthly sensor trends", "location": "l", "asset_tag": "TST-01",
                        "source_type": "sensor_trend_monthly", "text": (
                            "Monthly sensor trend for machine TST-01.\n"
                            "2026-03: 3720 observed readings (100.0% of expected 12-minute readings); mean vibration 2.100 mm/s, "
                            "maximum vibration 3.000 mm/s; mean temperature 40.00 C, maximum temperature 55.50 C.")})
        facts = {**facts_source(question, sources), "id": "S1"}
        self.assertIn("converted by code to Fahrenheit: mean temperature lowest 104.0 F", facts["text"])
        celsius = next(item for item in key_figures.required_from_facts(question, facts) if "Celsius" in item["label"])
        self.assertEqual(celsius["options"], ["Celsius"])
        self.assertFalse(key_figures.stated("41.0 °C", celsius["options"]))


if __name__ == "__main__":
    unittest.main()
