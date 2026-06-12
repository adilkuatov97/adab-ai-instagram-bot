from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services import claude_service


class ClaudeServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._original_client = claude_service._anthropic_client

    async def asyncTearDown(self):
        claude_service._anthropic_client = self._original_client

    async def test_valid_json_response(self):
        claude_service._anthropic_client = _FakeAnthropicClient(
            '{"reply":"Да, можем запустить аккуратно.","lead_temperature":"warm"}'
        )

        reply, is_hot_lead, temperature = await claude_service.ask_claude(
            "sender",
            "Сколько стоит?",
            _FakeClient(),
            [{"role": "user", "content": "Сколько стоит?"}],
        )

        self.assertEqual(reply, "Да, можем запустить аккуратно.")
        self.assertTrue(is_hot_lead)
        self.assertEqual(temperature, 1)

    async def test_plain_text_response_falls_back_to_text(self):
        claude_service._anthropic_client = _FakeAnthropicClient(
            "Понимаю. 5 дней — это срок на рабочий бот, не на сырой шаблон."
        )

        reply, is_hot_lead, temperature = await claude_service.ask_claude(
            "sender",
            "Конкуренты делают за 2 часа",
            _FakeClient(),
            [{"role": "user", "content": "Конкуренты делают за 2 часа"}],
        )

        self.assertEqual(reply, "Понимаю. 5 дней — это срок на рабочий бот, не на сырой шаблон.")
        self.assertFalse(is_hot_lead)
        self.assertEqual(temperature, 0)

    async def test_json_code_block_response(self):
        claude_service._anthropic_client = _FakeAnthropicClient(
            '```json\n{"reply":"Ок, передам менеджеру.","lead_temperature":"hot"}\n```'
        )

        reply, is_hot_lead, temperature = await claude_service.ask_claude(
            "sender",
            "Хочу купить",
            _FakeClient(),
            [{"role": "user", "content": "Хочу купить"}],
        )

        self.assertEqual(reply, "Ок, передам менеджеру.")
        self.assertTrue(is_hot_lead)
        self.assertEqual(temperature, 2)

    async def test_text_with_json_inside_response(self):
        claude_service._anthropic_client = _FakeAnthropicClient(
            'Вот ответ:\n{"reply":"Срок зависит от интеграций.","lead_temperature":"cold"}\nСпасибо'
        )

        reply, is_hot_lead, temperature = await claude_service.ask_claude(
            "sender",
            "Почему долго?",
            _FakeClient(),
            [{"role": "user", "content": "Почему долго?"}],
        )

        self.assertEqual(reply, "Срок зависит от интеграций.")
        self.assertFalse(is_hot_lead)
        self.assertEqual(temperature, 0)

    async def test_empty_response_returns_safe_fallback(self):
        claude_service._anthropic_client = _FakeAnthropicClient("")

        reply, is_hot_lead, temperature = await claude_service.ask_claude(
            "sender",
            "Привет",
            _FakeClient(),
            [{"role": "user", "content": "Привет"}],
        )

        self.assertEqual(reply, claude_service.EMPTY_CLAUDE_FALLBACK)
        self.assertFalse(is_hot_lead)
        self.assertEqual(temperature, 0)

    async def test_invalid_json_does_not_raise_json_decode_error(self):
        claude_service._anthropic_client = _FakeAnthropicClient('{"reply":')

        try:
            reply, is_hot_lead, temperature = await claude_service.ask_claude(
                "sender",
                "Привет",
                _FakeClient(),
                [{"role": "user", "content": "Привет"}],
            )
        except Exception as exc:  # pragma: no cover - assertion path
            self.fail(f"ask_claude raised unexpectedly: {exc!r}")

        self.assertEqual(reply, '{"reply":')
        self.assertFalse(is_hot_lead)
        self.assertEqual(temperature, 0)

    async def test_whatsapp_reply_is_truncated_to_700_chars(self):
        claude_service._anthropic_client = _FakeAnthropicClient("А" * 900)

        reply, is_hot_lead, temperature = await claude_service.ask_claude(
            "sender",
            "Привет",
            _FakeClient(),
            [{"role": "user", "content": "Привет"}],
            system_prompt_override="WHATSAPP RESPONSE POLICY",
        )

        self.assertLessEqual(len(reply), 700)
        self.assertFalse(is_hot_lead)
        self.assertEqual(temperature, 0)


class _FakeClient:
    whatsapp_link = ""
    system_prompt = "Base prompt"


class _FakeAnthropicClient:
    def __init__(self, text: str):
        self.messages = _FakeMessages(text)


class _FakeMessages:
    def __init__(self, text: str):
        self._text = text

    async def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


if __name__ == "__main__":
    unittest.main()
