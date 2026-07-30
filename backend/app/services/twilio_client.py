"""Twilio SMS and WhatsApp Notification Service Client for Amex ConciergeAI.

Handles dispatching real-time notifications to cardmembers with short-lived
signed JWT deep links allowing one-click rebooking approval or rejection.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import jwt
from twilio.rest import Client

from app.core.config import settings

logger = logging.getLogger("twilio_client")


class TwilioClient:
    """Dispatches rebooking confirmation requests to cardmembers via Twilio SMS."""

    def __init__(self) -> None:
        self.account_sid = settings.TWILIO_ACCOUNT_SID
        self.auth_token = settings.TWILIO_AUTH_TOKEN
        self.from_phone = settings.TWILIO_PHONE_NUMBER
        self._client: Optional[Client] = None

    @property
    def client(self) -> Client:
        """Lazy-loaded Twilio API helper instance."""
        if not self._client:
            # Bypass validation if mock credentials are set
            if self.account_sid == "mock_twilio_sid":
                self._client = None
            else:
                self._client = Client(self.account_sid, self.auth_token)
        return self._client

    def generate_signed_jwt_link(
        self,
        disruption_event_id: int,
        user_id: int,
        flight_option_id: str,
        hotel_option_id: Optional[str] = None,
        expires_in_minutes: int = 15
    ) -> str:
        """Generates a short-lived signed JWT rebooking deep link.

        Args:
            disruption_event_id: Database disruption identifier.
            user_id: Target cardmember.
            flight_option_id: Pre-selected alternative flight code.
            hotel_option_id: Optional selected hotel code.
            expires_in_minutes: TTL for token validation.

        Returns:
            The approval redirect query string token.
        """
        payload = {
            "disruption_event_id": disruption_event_id,
            "user_id": user_id,
            "flight_option_id": flight_option_id,
            "hotel_option_id": hotel_option_id,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
        }
        token = jwt.encode(
            payload,
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM
        )
        return token

    async def send_rebook_request(
        self,
        to_phone: str,
        user_id: int,
        disruption_event_id: int,
        flight_number: str,
        new_flight_number: str,
        new_price: float,
        token: str
    ) -> bool:
        """Dispatches rebooking notification text containing deep-links to user.

        Args:
            to_phone: Cardmember mobile phone contact number.
            user_id: Cardmember database identifier.
            disruption_event_id: Disruption reference ID.
            flight_number: Disrupted flight number.
            new_flight_number: Alternative flight number proposed.
            new_price: Proposed new flight price.
            token: Signed JWT token.

        Returns:
            True if text dispatched successfully, False otherwise.
        """
        # Deep links point to API redirect handlers
        base_host = "http://localhost:8000"  # Environment config or setting
        approve_link = f"{base_host}{settings.API_V1_STR}/disruptions/rebook/approve?token={token}"
        reject_link = f"{base_host}{settings.API_V1_STR}/disruptions/rebook/reject?token={token}"

        message_body = (
            f"Amex Concierge Alert: Your flight {flight_number} is disrupted.\n"
            f"We found an alternative flight: {new_flight_number} (Price: ${new_price:.2f}).\n\n"
            f"To APPROVE & book this alternative automatically, click here:\n{approve_link}\n\n"
            f"To REJECT & talk to a live concierge operator, click here:\n{reject_link}\n"
            f"Note: This proposal link expires in 15 minutes."
        )

        logger.info(f"Dispatched SMS content check to {to_phone} (disruption_event_id={disruption_event_id})")

        # Mock check
        if self.account_sid == "mock_twilio_sid" or not self.client:
            logger.info("[MOCK SMS DISPATCH SUCCESS] Content:\n" + message_body)
            return True

        try:
            # Non-blocking run in threadpool for sync Twilio helper
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.messages.create(
                    body=message_body,
                    from_=self.from_phone,
                    to=to_phone
                )
            )
            logger.info("Twilio SMS dispatched successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to send Twilio rebooking SMS: {e}")
            return False


# Singleton instance
twilio_service = TwilioClient()
