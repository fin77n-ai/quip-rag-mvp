import unittest
import asyncio
from unittest.mock import patch

from backend.services import llm_client


class _FakeClient:
    def __init__(self, error: Exception):
        self.error = error
        self.calls = 0

    def get_response(self, prompt: str):
        self.calls += 1
        raise self.error


class LLMClientTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        llm_client._quota_blocked_until = 0.0
        llm_client._quota_block_reason = ""

    def tearDown(self):
        llm_client._quota_blocked_until = 0.0
        llm_client._quota_block_reason = ""

    async def test_budget_exceeded_does_not_retry_and_opens_circuit(self):
        err = RuntimeError(
            "Request could go over budget, you have hit your daily cost allocation "
            "for quota 'personal:123' (current spend: $100.10 + estimated cost: $0.03 exceeds budget: $100.00)."
        )
        fake_client = _FakeClient(err)

        with patch.object(llm_client, "_get_client", return_value=fake_client):
            with self.assertRaises(llm_client.LLMQuotaExceededError):
                await llm_client.generate("hello")

            self.assertEqual(fake_client.calls, 1)

            with self.assertRaises(llm_client.LLMQuotaExceededError):
                await llm_client.generate("hello again")

            self.assertEqual(
                fake_client.calls,
                1,
                "Quota circuit should short-circuit follow-up calls without touching the client again.",
            )

    async def test_timeout_does_not_open_quota_circuit(self):
        fake_client = _FakeClient(asyncio.TimeoutError())

        with patch.object(llm_client, "_get_client", return_value=fake_client):
            with self.assertRaises(llm_client.LLMRequestTimeoutError):
                await llm_client.generate("large prompt")

        self.assertEqual(fake_client.calls, 1)
        self.assertEqual(llm_client._quota_blocked_until, 0.0)


if __name__ == "__main__":
    unittest.main()
