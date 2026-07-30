"""Database models module for the Amex ConciergeAI application.

This module defines the SQLAlchemy 2.0 declarative models for the data layer,
including User, DisruptionEvent, and AuditLog (XAI Audit Trail) entities.
"""

from datetime import datetime
from typing import Any, Dict, List
from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


class User(Base):
    """User representation representing an Amex cardmember.

    Attributes:
        id: Unique identifier for the user.
        email: Registered email of the user (unique and indexed).
        hashed_card_token: Tokenized/hashed credit card identifier (compliant with PII security).
        tier: Membership tier (e.g., PLATINUM, CENTURION).
        created_at: Timestamp indicating when the user profile was created.
        disruption_events: Associated disruption events for this user.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_card_token: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "PLATINUM", "CENTURION"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Relationships
    disruption_events: Mapped[List["DisruptionEvent"]] = relationship(
        "DisruptionEvent",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email='{self.email}' tier='{self.tier}'>"


class DisruptionEvent(Base):
    """DisruptionEvent representation tracking real-time travel disruptions.

    Attributes:
        id: Unique identifier for the disruption event.
        user_id: Foreign key mapping to the User.
        flight_number: The flight number affected (e.g., "AA123").
        original_departure: Original scheduled departure time.
        status: Progress state of the disruption workflow (DETECTED, PROCESSING, RESOLVED, ESCALATED).
        created_at: Timestamp indicating when the disruption was detected/created.
        user: The associated User model.
        audit_logs: Chronological list of audit decisions (XAI Audit Trail) for this event.
    """
    __tablename__ = "disruption_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    flight_number: Mapped[str] = mapped_column(String(50), nullable=False)
    original_departure: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        default="DETECTED",
        nullable=False
    )  # e.g., "DETECTED", "PROCESSING", "RESOLVED", "ESCALATED"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="disruption_events")
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="disruption_event",
        cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<DisruptionEvent id={self.id} user_id={self.user_id} "
            f"flight_number='{self.flight_number}' status='{self.status}'>"
        )


class AuditLog(Base):
    """AuditLog (XAI Audit Trail) representation tracking agent decisions.

    This captures the structured decisions made by the autonomous travel-disruption engine,
    documenting exactly why a flight selection or recommendation was made or dropped based on
    the hard filters and multi-factor scoring matrix.

    Weight Matrices for Scoring:
        - Price Delta: 40%
        - Travel Time: 25%
        - Alliance/Cabin: 20%
        - Layovers/Connections: 15%

    Attributes:
        id: Unique identifier for the audit log entry.
        disruption_event_id: Foreign key mapping to the DisruptionEvent.
        timestamp: Time when the decision was captured.
        decision_type: Type of action/decision (e.g., "HARD_FILTER_PASS", "RECOMMENDATION_SCORED", "ESCALATED_TO_HUMAN").
        reasoning_json: Structured explainable AI payload including filter status, scoring breakdown, and ranking details.
        created_at: Timestamp indicating when the record was inserted.
        disruption_event: The associated DisruptionEvent model.
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    disruption_event_id: Mapped[int] = mapped_column(
        ForeignKey("disruption_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    decision_type: Mapped[str] = mapped_column(String(100), nullable=False)
    reasoning_json: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Relationships
    disruption_event: Mapped["DisruptionEvent"] = relationship(
        "DisruptionEvent",
        back_populates="audit_logs"
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} disruption_event_id={self.disruption_event_id} "
            f"decision_type='{self.decision_type}'>"
        )
