"""AI-assisted exception suggestions.

The agent layer can propose values and explain them. It cannot record a review
decision, approve a batch, or write to a target system.
"""

from flowremote.agent.providers import (
    CustomerCandidate,
    OfflineSuggestionProvider,
    OpenAISuggestionProvider,
    ProviderError,
    SuggestedChange,
    SuggestionProvider,
    SuggestionRequest,
    SuggestionResponse,
    provider_from_env,
)

__all__ = [
    "CustomerCandidate",
    "OfflineSuggestionProvider",
    "OpenAISuggestionProvider",
    "ProviderError",
    "SuggestedChange",
    "SuggestionProvider",
    "SuggestionRequest",
    "SuggestionResponse",
    "provider_from_env",
]
