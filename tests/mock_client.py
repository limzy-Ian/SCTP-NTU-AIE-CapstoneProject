"""Mock chat clients for pipeline tests. No network, no key, no cost."""
from __future__ import annotations

from types import SimpleNamespace


class MockClient:
    """Returns the scripted replies in order. A reply that is an Exception instance is raised instead;\n    a callable reply is called with the create() keyword arguments and returns the text.

    ``calls`` holds the keyword arguments of every create() call, so tests can count calls and read prompts.
    """

    def __init__(self, replies, prompt_tokens=100, completion_tokens=20, with_usage=True):
        self.replies = list(replies)
        self.prompt_tokens, self.completion_tokens, self.with_usage = prompt_tokens, completion_tokens, with_usage
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if self.replies else "No more scripted replies."
        if callable(reply):
            reply = reply(kwargs)
        if isinstance(reply, Exception):
            raise reply
        usage = None
        if self.with_usage:
            usage = SimpleNamespace(prompt_tokens=self.prompt_tokens, completion_tokens=self.completion_tokens,
                                    total_tokens=self.prompt_tokens + self.completion_tokens)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))], usage=usage)


class ForbiddenClient:
    """Raises if the pipeline touches it. Used to prove a path makes no model call."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @staticmethod
    def _create(**kwargs):
        raise AssertionError("the model was called on a path that must not call it")
