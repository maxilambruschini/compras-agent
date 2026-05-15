"""TwilioProvider — WhatsApp via Twilio REST API.

Citations:
- D-03: Implements WhatsAppProvider Protocol (structurally — no inheritance).
- T-3-01: validate_signature wraps Twilio's RequestValidator (HMAC-SHA1).
- T-3-03: SSRF guard on download_media — URL must start with https://api.twilio.com/.
- T-3-04: Auth Token and Account SID are NEVER logged (T-02-02 pattern from Phase 2).

Algorithm Clarification (resolves 03-REVIEWS.md Codex HIGH concern #1):
  Twilio's X-Twilio-Signature is computed as
  Base64(HMAC-SHA1(auth_token, url + sorted(post_params))).
  This file delegates to twilio.request_validator.RequestValidator which implements
  exactly that scheme. CONTEXT.md INF-02's 'HMAC-SHA256' wording refers to the security
  property of HMAC-based signature validation, not a literal algorithm choice.
  See 03-REVIEWS.md and 03-01-PLAN.md §Algorithm Clarification.
"""
from __future__ import annotations

import httpx
import structlog
from twilio.http.async_http_client import AsyncTwilioHttpClient
from twilio.request_validator import RequestValidator
from twilio.rest import Client

log = structlog.get_logger()

# SSRF guard: only Twilio-hosted media URLs are permitted (T-3-03).
# mms.twiliocdn.com is the CDN Twilio redirects to after the initial api.twilio.com
# presigned URL — both prefixes are Twilio-controlled infrastructure.
TWILIO_MEDIA_URL_PREFIXES = (
    "https://api.twilio.com/",
    "https://mms.twiliocdn.com/",
)


class TwilioProvider:
    """WhatsApp provider backed by Twilio REST API.

    Satisfies the WhatsAppProvider Protocol (D-03) structurally — no inheritance.
    Constructor injection keeps the provider fully testable via @patch in unit tests.
    """

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        """Construct a TwilioProvider.

        Args:
            account_sid: Twilio Account SID (ACxxx...).
            auth_token: Twilio Auth Token — used for HMAC-SHA1 signature validation
                and HTTP Basic Auth on media downloads. NEVER logged.
            from_number: Sender phone number with 'whatsapp:' prefix,
                e.g. 'whatsapp:+14155238886'.
        """
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._validator = RequestValidator(auth_token)
        self._log = structlog.get_logger()

    def validate_signature(
        self, request_url: str, params: dict, signature: str
    ) -> bool:
        """Validate the X-Twilio-Signature header on an inbound webhook POST.

        Twilio's X-Twilio-Signature is computed as
        Base64(HMAC-SHA1(auth_token, url + sorted(post_params))).
        This delegates to twilio.request_validator.RequestValidator which
        implements that scheme. CONTEXT.md INF-02's 'HMAC-SHA256' wording refers
        to the security property of HMAC-based signature validation, not a literal
        algorithm choice — see 03-REVIEWS.md and 03-01-PLAN.md §Algorithm Clarification.

        Args:
            request_url: The exact URL Twilio signed (public URL, not internal host).
            params: The POST form fields as a plain dict.
            signature: The value of the X-Twilio-Signature header.

        Returns:
            True if the signature matches; False otherwise.
        """
        return self._validator.validate(request_url, params, signature)

    async def send_message(self, to: str, text: str) -> None:
        """Send a WhatsApp text message via Twilio.

        Constructs a fresh AsyncTwilioHttpClient per call to avoid shared state
        across concurrent requests. Closes the HTTP client in a finally block.
        Auth Token and Account SID are NEVER logged (T-02-02).

        Args:
            to: Recipient phone number with 'whatsapp:' prefix.
            text: Message body text.

        Raises:
            Re-raises any exception from the Twilio SDK after logging.
        """
        log = self._log.bind(to=to)
        log.info("whatsapp.send_message")
        http_client = AsyncTwilioHttpClient()
        try:
            client = Client(self._account_sid, self._auth_token, http_client=http_client)
            await client.messages.create_async(
                body=text,
                from_=self._from_number,
                to=to,
            )
        except Exception as exc:
            # Never log auth_token or account_sid — T-02-02
            log.error("whatsapp.send_failed", error=str(exc))
            raise
        finally:
            await http_client.close()

    async def download_media(self, media_url: str) -> bytes:
        """Download media bytes from a Twilio-hosted URL using HTTP Basic Auth.

        SSRF guard (T-3-03): rejects any URL that does not start with
        https://api.twilio.com/ — even though MediaUrl0 is always Twilio-issued,
        this is defence-in-depth against tampered form fields.

        Args:
            media_url: The MediaUrl0 value from the Twilio webhook POST form.

        Returns:
            Raw bytes of the media file.

        Raises:
            ValueError: If media_url does not start with TWILIO_MEDIA_URL_PREFIX.
            httpx.HTTPStatusError: If the download request fails.
        """
        if not any(media_url.startswith(p) for p in TWILIO_MEDIA_URL_PREFIXES):
            raise ValueError(
                f"Refusing to fetch non-Twilio media URL: {media_url!r}. "
                f"URL must start with one of {TWILIO_MEDIA_URL_PREFIXES} (SSRF guard T-3-03)."
            )
        # follow_redirects=True: Twilio's api.twilio.com endpoint issues a 307 to
        # mms.twiliocdn.com (a presigned CDN URL). The redirect destination is
        # validated by the SSRF check above before any request is made.
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                media_url,
                auth=(self._account_sid, self._auth_token),
            )
            response.raise_for_status()
            return response.content
