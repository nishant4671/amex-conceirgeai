# Amex ConciergeAI — System Implementation Roadmap & Phase Plan

## Phase 1: Foundation & Data Layer (Core Infrastructure)
- **Objective:** Establish the hybrid data persistence layer, configuration management, and security middleware.
- **Key Tasks:**
  - Initialize FastAPI project structure with environment validation via `pydantic-settings`.
  - Configure PostgreSQL connection pools and SQLAlchemy models (Users, AuditLogs, DisruptionEvents).
  - Configure Redis connection pools and LangGraph `AsyncRedisSaver` checkpointer.
  - Implement PII Masking middleware to intercept and scrub sensitive cardmember fields.
- **Verification Gate:** Docker-compose spins up Postgres and Redis successfully; health-check endpoints return 200 OK with active database pings.

## Phase 2: Core Engine & Deterministic Guardrails (The Brain)
- **Objective:** Build the deterministic business logic, hard filters, and multi-factor scoring matrix before introducing LLM agency.
- **Key Tasks:**
  - Implement the Hard Filter logic (filtering out flights exceeding card budgets or cabin downgrades).
  - Implement the Multi-Factor Scoring Matrix (Price Delta 40%, Travel Time 25%, Alliance 20%, Layovers 15%).
  - Build the Python rule-based deterministic fallback script (Dual Fallback Tier 1).
- **Verification Gate:** Automated unit tests verify that edge-case flight schedules are accurately filtered and scored within <50ms without errors.

## Phase 3: LangGraph State Machine & Agent Orchestration
- **Objective:** Construct the autonomous state machine and integrate the dual fallback stack.
- **Key Tasks:**
  - Build the LangGraph workflow: `Disruption_Detected` -> `Hard_Filters` -> `Scoring_Matrix` -> `Human_Approval_Interrupt` -> `Booking_Execution`.
  - Implement LLM timeout handlers (>3s trigger) and Amadeus API error catchers that reroute to the deterministic fallback stack.
  - Implement structured JSON Explainable AI (XAI) audit log emitters at every graph node transition.
- **Verification Gate:** State machine successfully pauses at the interrupt node, saves state to Redis, and successfully resumes upon mock webhook approval.

## Phase 4: Omnichannel Sync & External Integrations
- **Objective:** Wire up real-time WebSockets, Twilio deep-link delivery, and external travel APIs.
- **Key Tasks:**
  - Implement FastAPI WebSocket manager for live React dashboard state pushes.
  - Integrate Amadeus Flight API client with Redis 15-minute response caching.
  - Implement Twilio SMS/WhatsApp service generating short-lived Signed JWT deep-link URLs (`/rebook/approve?token=...`).
  - Implement state-sync broadcasting so approval on mobile instantly closes the web browser banner.
- **Verification Gate:** End-to-end integration test confirms an incoming disruption triggers a WebSocket push and an SMS with a working JWT deep link.

## Phase 5: Human-in-the-Loop (HITL) Escalation & Concierge Portal
- **Objective:** Implement the live chat handoff and human operator dashboard integration.
- **Key Tasks:**
  - Build the WebSocket escalation router for routing failed/rejected flows to human agents.
  - Create the serialized LangGraph context hydration payload so human operators instantly view AI reasoning history.
  - Implement unattended fallback queueing if a human agent does not accept within 15 seconds.
- **Verification Gate:** Clicking "Talk to a Human" instantly shifts the session stream and populates the operator dashboard with complete context history.

## Phase 6: Hardening, Polish & Submission Packaging
- **Objective:** Final code audit, security check, performance benchmarking, and presentation asset finalization.
- **Key Tasks:**
  - Run full type-checking (`mypy`) and linting across the codebase.
  - Verify zero plaintext PII storage or logging.
  - Package Dockerfiles for streamlined local demo execution.
- **Verification Gate:** Clean build with zero errors, fully operational local containerized stack ready for live demonstration.
