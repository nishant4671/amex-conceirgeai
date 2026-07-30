# Amex ConciergeAI — System Technical Master Report & Handover Manual

## 1. System Architecture Overview & Core Components
- **Architecture Style:** Clean Architecture separating API Routing from Orchestration and Core Deterministic Engines:
  - **API Gateway & Routing Layer:** FastAPI routers managing incoming requests and WebSocket sessions.
  - **Service Integration Layer:** Downstream clients handling database sessions, Redis caches, Amadeus travel queries, and Twilio SMS.
  - **Core Engines:** Isolated Python libraries managing mathematical scoring and hard data filters.
- **Technology Stack:**
  - **Core Runtime:** Python 3.11+
  - **Application Framework:** FastAPI (v0.111.0) & Pydantic v2 (v2.7.4)
  - **ORM & Data Layer:** SQLAlchemy 2.0 (v2.0.31) & Asyncpg (v0.29.0)
  - **Agent State Machine:** LangGraph (v1.2.10)
  - **Caching & Persistence:** Redis (v7.4.1) & PostgreSQL (v15)
  - **Deployment Packaging:** Docker & Docker Compose
- **Component Mapping:**
  - FastAPI captures disruption alerts and dispatches async tasks.
  - LangGraph directs state progression using [AgentState](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/agent/state.py#L10) and handles execution checkpoints in Redis via [AsyncRedisSaver](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/services/redis_client.py#L27).
  - PostgreSQL manages permanent relational data models ([User](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/models/sql_models.py#L19), [DisruptionEvent](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/models/sql_models.py#L47), and [AuditLog](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/models/sql_models.py#L84)), housing structured explainable AI logs.

---

## 2. Deterministic Guardrails & Core Engine Specification
- **Hard Filters ([filters.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/engine/filters.py)):**
  - **Spend Caps:** Evaluates candidates against relative tier guidelines (Platinum allows up to +50% of the original flight cost; Centurion allows up to +150% increase) alongside absolute maximum budget rules ($2000 for Platinum, $5000 for Centurion).
  - **Cabin Entitlements:** Prevents cabin class downgrades using a hierarchical class ranking system (`ECONOMY`, `PREMIUM_ECONOMY`, `BUSINESS`, `FIRST`). Candidates that do not meet the minimum rank of the disrupted flight are automatically dropped.
  - **Dropped Logs:** Every drop populates a structured audit payload containing the target option ID and the validation failure explanation.
- **Multi-Factor Scoring Matrix ([scoring.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/engine/scoring.py)):**
  - **Scoring Weights:** Ranks surviving compliant candidates based on a composite score ($S$) totaling:
    - **Price Delta ($40\%$)**: Prefers options closer to or cheaper than original.
    - **Total Travel Time ($25\%$)**: Normalized ranking preferring shorter durations.
    - **Alliance / Cabin Match ($20\%$)**: Rewards existing loyalty programs (OneWorld, Star Alliance, SkyTeam) and cabin class upgrades.
    - **Layover Count & Duration ($15\%$)**: Prefers direct routing and minimal transfer periods.
  - **XAI Explanation Output:** Returns a dictionary detailing raw sub-scores and weighted sub-scores to document choices for auditing.
- **Dual Fallback Stack ([fallback.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/engine/fallback.py) & [runner.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/agent/runner.py)):**
  - **Timeout Protection:** The orchestrator wraps the workflow execution in an `asyncio.timeout(3.0)` block.
  - **Tier 1 Degradation:** If the async workflow times out (>3 seconds) or throws an exception, it triggers [execute_fallback_pipeline](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/engine/fallback.py#L31) to complete filtering and scoring within `<50ms` using standard Python logic.

---

## 3. Data Schema & Persistence Specifications
- **Relational Tables (PostgreSQL):**
  - `users`: ID, unique email, hashed credit card token reference, and membership tier string.
  - `disruption_events`: ID, user foreign key, flight number, original departure timestamp, and status.
  - `audit_logs`: ID, disruption event foreign key, timestamp, decision type, and a structured `reasoning_json` column housing XAI summaries.
- **State Checkpointing (Redis):**
  - **LangGraph Checkpointer:** Uses `AsyncRedisSaver` to save workflow checkpoints indexed by `thread_id` (e.g. `disruption-{event_id}`).
  - **Response Cache:** Houses Amadeus Flight API query JSON strings with a 15-minute Time-To-Live (TTL) limit (`ex=900`) to prevent API rate-limiting.
  - **WebSocket Channel Sync:** WebSockets track active connections mapping to specific cardmembers for streaming updates.

---

## 4. Omnichannel Integration & Security Protocols
- **PII Masking Layer ([security.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/core/security.py)):**
  - Employs regex filters matching Credit Cards, Passports, and Email signatures to sanitize all logged payloads.
  - [mask_payload](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/core/security.py#L54) recursively masks dictionary structures containing sensitive billing keys.
- **Stateless JWT Deep Links ([twilio_client.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/services/twilio_client.py)):**
  - Generates signed JWTs encoded with `disruption_event_id`, `user_id`, `flight_option_id`, and a short `exp` expiration window (15 minutes).
  - Appends this token to `/rebook/approve?token=...` links sent via SMS, allowing 1-click mobile rebooking approvals.
- **WebSocket State Synchronization ([disruptions.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/api/disruptions.py)):**
  - The [WebSocketManager](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/api/disruptions.py#L22) broadcasts state transitions to all open UI panels. Approving or escalating closes outstanding rebooking screens immediately.

---

## 5. Human-in-the-Loop (HITL) Escalation & Operator Portal
- **Context Hydration ([escalation.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/services/escalation.py)):**
  - Merges the disruption event details, user profile, and history of filter choices and scoring outputs from the database into a single JSON dashboard payload.
- **SLA Queue Management:**
  - Spawns a background task ([check_unattended_sla](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/services/escalation.py#L88)) when a ticket is escalated. If no operator claims it within **15 seconds**, it updates the ticket status to `VIP_AUTO_ROUTED`, logs an SLA alert, and informs the user UI.
- **Operator Endpoints ([concierge.py](file:///C:/Users/HP/OneDrive/Desktop/amex-conceirgeai/backend/app/api/concierge.py)):**
  - `/concierge/queue`: Lists escalated disruption sessions.
  - `/concierge/claim/{event_id}`: Assigns the event to an operator, updates its status, and returns the hydrated context payload.

---

## 6. Testing, Deployment & Operational Playbook
- **Test Suite Execution:**
  - Execute tests using pytest within the virtual environment:
    ```bash
    cd backend
    ..\.venv\Scripts\python -m pytest
    ```
  - Validates hard filters, scoring matrices, fallback engines, API endpoints, and WebSocket channels.
- **Container Orchestration:**
  - Launch the Postgres database, Redis cache, and FastAPI Backend:
    ```bash
    docker-compose up --build
    ```
- **Future Roadmap & Maintenance:**
  - **GDS Integration:** Swap out Amadeus shopping integrations for live Sabre/Amadeus GDS rebooking connections.
  - **PNR Cabin Splits:** Support PNR routing separations for multi-passenger bookings.
