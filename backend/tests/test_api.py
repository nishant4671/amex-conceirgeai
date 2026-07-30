"""Integration tests for FastAPI REST & WebSocket endpoints."""

import jwt
from unittest.mock import AsyncMock, MagicMock, patch

# Start database session and connection patches globally for test environment
session_patcher = patch("app.services.database.AsyncSessionLocal")
mock_session_local = session_patcher.start()
mock_session_local.return_value.__aenter__.return_value = AsyncMock()

db_conn_patcher = patch("app.services.database.verify_db_connection", return_value=True)
db_conn_patcher.start()

redis_conn_patcher = patch("app.services.redis_client.verify_redis_connection", return_value=True)
redis_conn_patcher.start()

from fastapi.testclient import TestClient
from app.core.config import settings
from app.models.schemas import CardTier
from app.models.sql_models import User
from app.services.database import get_db
from app.services.twilio_client import twilio_service
from main import app

# Mock database session for request dependency injection
async def mock_get_db():
    mock_session = AsyncMock()
    mock_user = User(id=99, email="member_99@amex.com", tier=CardTier.PLATINUM.value)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_user
    mock_session.execute.return_value = mock_execute_result
    
    yield mock_session

# Apply override
app.dependency_overrides[get_db] = mock_get_db

client = TestClient(app)


def test_health_check_endpoint():
    """Verify that the health check endpoint returns 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()
    assert "services" in response.json()


def test_trigger_disruption_endpoint():
    """Verify that triggering a disruption responds with 202 Accepted."""
    payload = {
        "user_id": 99,
        "flight_number": "AA123",
        "original_price": 500.0,
        "original_cabin": "ECONOMY",
        "original_alliance": "OneWorld",
        "user_phone": "+1234567890"
    }
    response = client.post("/api/v1/disruptions/trigger", json=payload)
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "PROCESSING"
    assert "disruption_event_id" in data


def test_rebook_approve_invalid_token():
    """Verify that approve endpoint fails when using an invalid JWT signature."""
    response = client.get("/api/v1/disruptions/rebook/approve?token=invalid_jwt_signature")
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token verification."


def test_rebook_approve_expired_token():
    """Verify that approve endpoint fails when using an expired JWT signature."""
    from datetime import datetime, timedelta, timezone
    expired_payload = {
        "disruption_event_id": 1,
        "user_id": 99,
        "flight_option_id": "FL-01",
        "exp": datetime.now(timezone.utc) - timedelta(minutes=10)  # Expired
    }
    expired_token = jwt.encode(expired_payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    
    response = client.get(f"/api/v1/disruptions/rebook/approve?token={expired_token}")
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_websocket_connection():
    """Verify that a client can establish a WebSocket connection and listen for updates."""
    with client.websocket_connect("/api/v1/disruptions/ws/99") as websocket:
        # Send keeping alive message
        websocket.send_text("ping")
        # Connection should stay active without throwing errors
