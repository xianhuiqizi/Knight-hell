"""Provider contracts do not require a network and never guess customer IDs."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flowremote.agent.providers import (
    CustomerCandidate,
    OfflineSuggestionProvider,
    OpenAISuggestionProvider,
    ProviderError,
    SuggestionRequest,
)


def request(*, candidates=(), flagged=("customer_id",), quantity="2", amount="19"):
    return SuggestionRequest(
        task_id="TASK-1",
        record_id="ORD-001",
        issue_codes=("missing_value",),
        flagged_fields=flagged,
        current_values={
            "order_id": "A",
            "customer_name": "Alex Example",
            "customer_id": "",
            "quantity": quantity,
            "unit_price": "10",
            "amount": amount,
            "order_date": "2026-10-20",
        },
        candidates=tuple(candidates),
    )


class OfflineProviderTests(unittest.TestCase):
    def test_unique_registry_match_produces_a_grounded_customer_id(self):
        result = OfflineSuggestionProvider().suggest(
            request(candidates=[CustomerCandidate("C-01", "Alex Example")])
        )
        self.assertEqual(result.changes[0].field, "customer_id")
        self.assertEqual(result.changes[0].value, "C-01")
        self.assertIn("customer_registry:C-01", result.changes[0].evidence)

    def test_no_candidate_produces_no_customer_guess(self):
        result = OfflineSuggestionProvider().suggest(request())
        self.assertEqual(result.changes, ())
        self.assertIn("No reliable suggestion", result.message)

    def test_ambiguous_candidates_do_not_identify_a_customer(self):
        result = OfflineSuggestionProvider().suggest(
            request(
                candidates=[
                    CustomerCandidate("C-01", "Alex Example"),
                    CustomerCandidate("C-02", "Alex Example"),
                ]
            )
        )
        self.assertEqual(result.changes, ())

    def test_arithmetic_amount_can_be_grounded_in_the_row(self):
        result = OfflineSuggestionProvider().suggest(
            request(flagged=("amount",), quantity="2", amount="19")
        )
        self.assertEqual(result.changes[0].value, "20.00")

    def test_missing_api_key_is_reported_without_a_request(self):
        with self.assertRaises(ProviderError):
            OpenAISuggestionProvider(api_key="").suggest(request())

    def test_structured_output_is_converted_to_the_provider_contract(self):
        parsed = SimpleNamespace(
            changes=[
                SimpleNamespace(
                    field="customer_id",
                    value="C-01",
                    confidence=0.95,
                    reason="Unique registry match.",
                    evidence=["customer_registry:C-01"],
                )
            ],
            message="One grounded suggestion.",
            model_dump=lambda: {"changes": [{"field": "customer_id"}], "message": "ok"},
        )

        class Responses:
            def parse(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(output_parsed=parsed)

        class Client:
            def __init__(self):
                self.responses = Responses()

        client = Client()
        with patch("openai.OpenAI", return_value=client):
            result = OpenAISuggestionProvider(
                api_key="test-key", model="test-model"
            ).suggest(request(candidates=[CustomerCandidate("C-01", "Alex Example")]))
        self.assertEqual(result.changes[0].field, "customer_id")
        self.assertEqual(result.changes[0].value, "C-01")
        self.assertEqual(client.responses.kwargs["text_format"].__name__, "ModelSuggestion")


if __name__ == "__main__":
    unittest.main()
