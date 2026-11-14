"""Phase 6: the Streamlit Assistant tab on the pipeline: outcome badge, notes box, cost, budget, request log.

MySQL and the model are replaced by fakes; the chat store keeps what the app saves, so the rerun shows the saved turn.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from jm_rag import config
from jm_rag.guardrails import names
from tests.fixtures import build_fixture_sources

APP = str(Path(__file__).resolve().parents[1] / "app.py")
ENV = {"OPENAI_API_KEY": "sk-test-not-a-real-key-000000000000", "OPENAI_MODEL": "test-model",
       "OPENAI_INPUT_COST_PER_1M_USD": "1.00", "OPENAI_OUTPUT_COST_PER_1M_USD": "2.00"}


class AppTests(unittest.TestCase):
    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def run_app(self, question, reply=None, env_extra=None, spent_today=0.0):
        from streamlit.testing.v1 import AppTest

        store, calls = [], {"model": 0}

        class FakeOpenAI:
            def __init__(self, *args, **kwargs):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

            def create(self, **kwargs):
                calls["model"] += 1
                if reply is None:
                    raise AssertionError("the model was called")
                usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100, total_tokens=1100)
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))], usage=usage)

        def append(connection, chat_id, user, answer, sources, tokens, cost_usd=None, outcome=None):
            store.extend([{"role": "user", "content": user, "sources": [], "token_count": 0},
                          {"role": "assistant", "content": answer, "sources": sources, "token_count": tokens,
                           "cost_usd": cost_usd, "outcome": outcome}])

        summary = {name: {"chat": {"cost_usd": spent_today}, "eval": {"cost_usd": 0.0}, "total_usd": spent_today}
                   for name in ("today", "last_7_days", "all_time")}
        with patch.dict("os.environ", {**ENV, **(env_extra or {})}), patch.object(config, "ROOT", Path(self.temp.name)), \
                patch("scripts.ocr_review.open_connection", return_value=MagicMock()), \
                patch("scripts.chat_history.ensure_chat_schema"), \
                patch("scripts.chat_history.list_chats", side_effect=lambda c: [{"chat_id": "c1", "title": "t"}] if store else []), \
                patch("scripts.chat_history.load_chat_messages", side_effect=lambda c, chat_id: list(store)), \
                patch("scripts.chat_history.create_chat", return_value="c1"), \
                patch("scripts.chat_history.append_chat_turn", side_effect=append), \
                patch("jm_rag.observability.spend_summary", return_value=summary), \
                patch("openai.OpenAI", FakeOpenAI), \
                patch("scripts.maintenance_rag.load_sources", return_value=(build_fixture_sources(), [])), \
                patch("dotenv.load_dotenv"):
            app = AppTest.from_file(APP, default_timeout=120)
            app.run()
            app.chat_input[0].set_value(question).run()
            self.assertEqual(len(app.exception), 0, [str(error.value)[:300] for error in app.exception])
        markdown = " ".join(str(element.value) for element in app.markdown)
        captions = " ".join(str(element.value) for element in app.caption)
        metrics = {element.label: element.value for element in app.metric}
        info = " ".join(str(element.value) for element in app.info)
        errors = " ".join(str(element.value) for element in app.error)
        warnings = " ".join(str(element.value) for element in app.warning)
        log = Path(self.temp.name) / "logs" / "requests.jsonl"
        requests = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
        return SimpleNamespace(markdown=markdown, captions=captions, metrics=metrics, info=info, errors=errors,
                               warnings=warnings, store=store, calls=calls, requests=requests)

    def test_a_model_answer_shows_the_badge_the_notes_box_and_its_cost(self):
        page = self.run_app("what is the serial number of TST-02", reply="The serial number is SN-FAKE-02 [S1].")
        self.assertEqual(page.calls["model"], 1)
        self.assertIn(":green-badge[Answer]", page.markdown)
        self.assertIn("The serial number is SN-FAKE-02 [S1].", page.markdown)
        self.assertIn("not human-verified", page.info)
        self.assertIn("Notes added by code", page.info)
        self.assertIn("This answer: 1100 tokens, $0.001200", page.captions)
        self.assertEqual(page.metrics["Last answer cost"], "$0.001200")
        self.assertEqual(page.metrics["Session total"], "$0.001200")
        self.assertIn("Today (all users and evals)", page.metrics)
        self.assertAlmostEqual(page.store[1]["cost_usd"], 0.0012)
        self.assertEqual(page.store[1]["outcome"], "answer")

    def test_a_refusal_shows_the_refusal_text_and_no_cost(self):
        page = self.run_app("Give me the names of everyone injured in 2025.")
        self.assertEqual(page.calls["model"], 0)
        self.assertIn(":red-badge[Refused]", page.markdown)
        self.assertIn("I cannot give out names", page.markdown)
        self.assertIn("No model call for this answer", page.captions)
        self.assertEqual(page.store[1]["outcome"], "refuse")

    def test_an_abstain_and_a_conflict_show_their_badges(self):
        page = self.run_app("show work orders for TST-99")
        self.assertIn(":violet-badge[Cannot answer fully]", page.markdown)
        page = self.run_app("what model is TST-02", reply="The plate reads Mill Beta 250 [S1].")
        self.assertIn(":orange-badge[Conflict]", page.markdown)
        self.assertIn("Mill Beta 200", page.info)

    def test_each_question_writes_one_request_line_without_text(self):
        page = self.run_app("what is the serial number of TST-01", reply="The serial number is SN-FAKE-01 [S1].")
        self.assertEqual(len(page.requests), 1)
        entry = page.requests[0]
        self.assertEqual((entry["outcome"], entry["calls"], entry["chat_id"]), ("answer", 1, None))
        self.assertAlmostEqual(entry["cost_usd"], 0.0012)
        self.assertNotIn("serial", json.dumps(entry))

    def test_the_budget_warning_appears_at_80_percent(self):
        page = self.run_app("show work orders for TST-01", env_extra={"DAILY_BUDGET_USD": "1.00"}, spent_today=0.85)
        self.assertIn("Daily budget: $0.8500 of $1.00 used", page.warnings)
        self.assertIn("Over 80% used", page.warnings)

    def test_at_the_budget_limit_no_model_is_called_and_code_answers(self):
        page = self.run_app("what is the serial number of TST-01", reply="never used", env_extra={"DAILY_BUDGET_USD": "1.00"},
                            spent_today=1.00)
        self.assertEqual(page.calls["model"], 0)
        self.assertIn("The model budget is used up", page.errors)
        self.assertIn("model budget is used up", page.info)
        self.assertIn("no AI wording was generated", page.markdown)

    def test_without_a_limit_there_is_no_budget_message(self):
        page = self.run_app("show work orders for TST-01", spent_today=100.0)
        self.assertNotIn("budget", page.warnings + page.errors)


if __name__ == "__main__":
    unittest.main()
