"""The optional review AI must be bounded, parseable and key-safe."""

from __future__ import annotations

import json
from unittest import TestCase

import httpx

from flowremote.agent.normalization_ai import (
    NormalizationAIError,
    parse_ai_payload,
    suggest_with_ai,
)


def transport(handler):
    return httpx.MockTransport(handler)


CONTEXT = {
    "issue": {"type": "missing_value", "field": "customer_id"},
    "current": {"customer_id": "", "customer_name": "Delta Works"},
    "allowed_fields": [
        "customer_id",
        "customer_name",
        "quantity",
        "unit",
        "unit_price",
        "amount",
        "order_date",
    ],
    "alternatives": [{"customer_id": "C-2104", "customer_name": "Delta Works"}],
}


class ParseReviewAIPayloadTests(TestCase):
    def test_fenced_json_is_parsed_and_unknown_fields_are_dropped(self):
        result = parse_ai_payload(
            """```json
            {"fields": {"customer_id": "C-2104", "order_id": "ORD-HACK"},
             "confidence": 0.91, "reason": "Unique match", "evidence": ["one row"]}
            ```""",
            {"customer_id", "quantity"},
        )
        self.assertEqual(result.fields, {"customer_id": "C-2104"})
        self.assertEqual(result.confidence, 0.91)
        self.assertEqual(result.reason, "Unique match")
        self.assertEqual(result.evidence, ("one row",))

    def test_invalid_json_is_a_safe_error(self):
        with self.assertRaises(NormalizationAIError) as caught:
            parse_ai_payload("not json", {"customer_id"})
        self.assertEqual(caught.exception.code, "invalid_response")

    def test_confidence_is_clamped(self):
        result = parse_ai_payload(
            json.dumps({"fields": {}, "confidence": 7, "reason": "unsure"}),
            {"customer_id"},
        )
        self.assertEqual(result.confidence, 1.0)


class SuggestWithAITests(TestCase):
    def test_chat_completions_request_success(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "fields": {"customer_id": "C-2104"},
                                        "confidence": 0.9,
                                        "reason": "Matched by customer name.",
                                        "evidence": ["one matching row"],
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        result = suggest_with_ai(
            CONTEXT,
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            api_key="sk-secret-value",
            transport=transport(handler),
        )
        self.assertEqual(result.fields, {"customer_id": "C-2104"})
        self.assertEqual(result.model, "deepseek-flash")
        self.assertEqual(seen["url"], "https://api.deepseek.com/v1/chat/completions")
        self.assertEqual(seen["auth"], "Bearer sk-secret-value")
        self.assertEqual(seen["body"]["model"], "deepseek-flash")
        self.assertIn("system", seen["body"]["messages"][0]["role"])
        self.assertNotIn("sk-secret-value", json.dumps(result.fields))

    def test_401_is_classified_without_echoing_key(self):
        def handler(request):
            return httpx.Response(401, json={"error": {"message": "bad key"}})

        with self.assertRaises(NormalizationAIError) as caught:
            suggest_with_ai(
                CONTEXT,
                model="deepseek-flash",
                base_url="https://api.deepseek.com",
                api_key="sk-secret-value",
                transport=transport(handler),
            )
        self.assertEqual(caught.exception.code, "invalid_key")
        self.assertNotIn("sk-secret-value", str(caught.exception))

    def test_429_and_timeout_are_safe(self):
        def limited(request):
            return httpx.Response(429, json={"error": "quota"})

        with self.assertRaises(NormalizationAIError) as caught:
            suggest_with_ai(
                CONTEXT,
                model="deepseek-flash",
                base_url="https://api.deepseek.com",
                api_key="sk-secret-value",
                transport=transport(limited),
            )
        self.assertEqual(caught.exception.code, "quota")

        def slow(request):
            raise httpx.ReadTimeout("timeout", request=request)

        with self.assertRaises(NormalizationAIError) as caught:
            suggest_with_ai(
                CONTEXT,
                model="deepseek-flash",
                base_url="https://api.deepseek.com",
                api_key="sk-secret-value",
                transport=transport(slow),
            )
        self.assertEqual(caught.exception.code, "network")

    def test_empty_key_is_rejected_before_network(self):
        with self.assertRaises(NormalizationAIError) as caught:
            suggest_with_ai(
                CONTEXT,
                model="deepseek-flash",
                base_url="https://api.deepseek.com",
                api_key="",
                transport=transport(lambda request: httpx.Response(200)),
            )
        self.assertEqual(caught.exception.code, "no_key")
