"""MetaCloudProvider stub — WhatsApp via Meta Cloud API (future implementation).

Citations:
- D-03: Satisfies WhatsAppProvider Protocol structurally (no inheritance).

This is a placeholder stub. Set WHATSAPP_PROVIDER=twilio to use the active
Twilio implementation. MetaCloudProvider will be wired in Phase 4 or a future sprint.

Every method raises NotImplementedError so any accidental use fails loudly.
"""
from __future__ import annotations


class MetaCloudProvider:
    """WhatsApp provider stub for Meta Cloud API.

    Satisfies the WhatsAppProvider Protocol (D-03) structurally.
    All methods raise NotImplementedError — this is intentional.
    Set WHATSAPP_PROVIDER=twilio for the active implementation.
    """

    def __init__(self, **_kwargs: object) -> None:
        """Accept (and ignore) any keyword args so the factory can pass Settings fields
        without coupling this stub to the Settings schema."""
        pass

    async def send_message(self, to: str, text: str) -> None:
        """Not implemented. Set WHATSAPP_PROVIDER=twilio."""
        raise NotImplementedError(
            "MetaCloudProvider is a stub — set WHATSAPP_PROVIDER=twilio"
        )

    async def download_media(self, media_url: str) -> bytes:
        """Not implemented. Set WHATSAPP_PROVIDER=twilio."""
        raise NotImplementedError(
            "MetaCloudProvider is a stub — set WHATSAPP_PROVIDER=twilio"
        )

    def validate_signature(
        self, request_url: str, params: dict, signature: str
    ) -> bool:
        """Not implemented. Set WHATSAPP_PROVIDER=twilio."""
        raise NotImplementedError(
            "MetaCloudProvider is a stub — set WHATSAPP_PROVIDER=twilio"
        )
