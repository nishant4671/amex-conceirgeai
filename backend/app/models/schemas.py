"""Pydantic schemas module for the Amex ConciergeAI application.

This module defines Pydantic v2 schemas for request/response validation and
serialization of Users, Disruption Events, and XAI Audit Logs.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CardTier(str, Enum):
    """Membership tier options for Amex cardmembers."""
    PLATINUM = "PLATINUM"
    CENTURION = "CENTURION"


class DisruptionStatus(str, Enum):
    """Execution status states for travel disruption events."""
    DETECTED = "DETECTED"
    PROCESSING = "PROCESSING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


# ==========================================
# User Schemas
# ==========================================

class UserBase(BaseModel):
    """Base schema properties shared across user inputs and outputs."""
    email: EmailStr = Field(..., description="The registered email of the cardmember.")
    tier: CardTier = Field(default=CardTier.PLATINUM, description="The membership tier of the cardmember.")


class UserCreate(UserBase):
    """Schema for validating user creation payloads."""
    hashed_card_token: str = Field(
        ...,
        description="The hashed or tokenized card representation. Plain-text credit cards must never be passed.",
        min_length=8
    )


class UserResponse(UserBase):
    """Schema for returning user representation responses."""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="The database primary key identifier.")
    created_at: datetime = Field(..., description="The UTC timestamp when the user profile was created.")


# ==========================================
# DisruptionEvent Schemas
# ==========================================

class DisruptionEventBase(BaseModel):
    """Base schema properties shared across disruption inputs and outputs."""
    flight_number: str = Field(..., description="The flight code that was disrupted (e.g. 'AA123').", min_length=2, max_length=50)
    original_departure: datetime = Field(..., description="The originally scheduled departure time.")
    status: DisruptionStatus = Field(default=DisruptionStatus.DETECTED, description="The status of the disruption process.")


class DisruptionEventCreate(DisruptionEventBase):
    """Schema for creating/detecting a new disruption event payload."""
    user_id: int = Field(..., description="The target cardmember's database identifier.")


class DisruptionEventUpdate(BaseModel):
    """Schema for updating the status of an existing disruption event."""
    status: DisruptionStatus = Field(..., description="The new status of the disruption event.")


class DisruptionEventResponse(DisruptionEventBase):
    """Schema for returning disruption event details."""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="The database primary key identifier.")
    user_id: int = Field(..., description="The associated user's database identifier.")
    created_at: datetime = Field(..., description="The UTC timestamp when this disruption was detected.")


# ==========================================
# AuditLog (XAI Audit Trail) Schemas
# ==========================================

class AuditLogBase(BaseModel):
    """Base schema properties shared across XAI audit log inputs and outputs."""
    decision_type: str = Field(
        ...,
        description="Type of decision action (e.g., 'HARD_FILTER_PASS', 'RECOMMENDATION_SCORED').",
        min_length=1,
        max_length=100
    )
    reasoning_json: Dict[str, Any] = Field(
        ...,
        description="Structured JSON details containing score breakdown or filter logs."
    )


class AuditLogCreate(AuditLogBase):
    """Schema for creating a new audit trail entry."""
    disruption_event_id: int = Field(..., description="The related disruption event identifier.")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="The timestamp of the decision event.")


class AuditLogResponse(AuditLogBase):
    """Schema for returning XAI audit log details."""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="The database primary key identifier.")
    disruption_event_id: int = Field(..., description="The associated disruption event identifier.")
    timestamp: datetime = Field(..., description="The timestamp of the logged decision.")
    created_at: datetime = Field(..., description="The UTC timestamp when this record was stored.")


# ==========================================
# Deep Hydrated/Relationship Schemas
# ==========================================

class UserWithEvents(UserResponse):
    """User response object hydrated with their disruption events."""
    disruption_events: List[DisruptionEventResponse] = []


class DisruptionEventDetailed(DisruptionEventResponse):
    """Disruption event response hydrated with associated user details and full XAI audit logs."""
    user: UserResponse
    audit_logs: List[AuditLogResponse] = []
