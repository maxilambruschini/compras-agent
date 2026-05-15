"""WhatsAppProvider Protocol — provider-agnostic WhatsApp interface.

Citations:
- D-03: Provider abstraction: WhatsApp gateway as a Protocol so the router never
        imports twilio or pywa directly. Swap implementation via env var at startup.

Why Protocol not ABC (same rationale as StorageBackend in services/storage.py):
  - No forced inheritance — TwilioProvider satisfies Protocol structurally.
  - @runtime_checkable allows isinstance(provider, WhatsAppProvider) in tests.
  - Matches the established Python service-layer pattern used in Phase 2.

Implementations: TwilioProvider (demo), MetaCloudProvider (production stub).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class WhatsAppProvider(Protocol):
    """Provider-agnostic WhatsApp interface (D-03).

    Implementations: TwilioProvider (demo), MetaCloudProvider (production stub).
    Handler code imports only this protocol — never twilio or pywa directly.
    """

    async def send_message(self, to: str, text: str) -> None:
        """Send a WhatsApp text message to the given phone number."""
        ...

    async def download_media(self, media_url: str) -> bytes:
        """Download media bytes from the provider-specific URL."""
        ...

    def validate_signature(
        self, request_url: str, params: dict, signature: str
    ) -> bool:
        """Validate the webhook request signature. Synchronous (CPU-bound)."""
        ...
