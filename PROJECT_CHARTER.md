# Amex ConciergeAI — Project Charter & Technical Specification

## 1. Executive Summary & Business Motive
- **Project Name:** Amex ConciergeAI (Autonomous Travel-Disruption Resolution Engine).
- **Core Motive:** Transform travel disruption handling from a high-friction, manual, call-center-heavy process into an autonomous, sub-5-second, 1-click resolution pipeline for premium cardmembers.
- **Business ROI:** Eliminates high operational costs (benchmarked at ~$18 per human support interaction) and prevents friction-based benefit abandonment, protecting Net Promoter Scale (NPS) and Customer Lifetime Value (LTV).

## 2. Scope & Boundaries
- **In-Scope (Hackathon / Phase 2 MVP):**
  - Real-time flight disruption detection (Smart Polling + Webhook stub).
  - Bounded AI state machine using LangGraph with AsyncRedisSaver persistence.
  - Two-Step Pipeline: Absolute Hard Filters -> Multi-Factor Scoring Matrix (Price 40%, Time 25%, Alliance/Cabin 20%, Layovers 15%).
  - Multi-Channel Approval Sync: In-App React WebSockets + Twilio SMS/WhatsApp with signed JWT deep links.
  - Dual Fallback Stack: Automated degradation to deterministic Python rules and Redis cached data upon API/LLM failure.
  - Enterprise Governance: PII Masking layer and structured JSON Explainable AI (XAI) audit logging.
  - Human-in-the-Loop (HITL) Escalation: WebSocket chat transfer to AmEx Concierge Agent Portal with hydrated LangGraph memory.
- **Out-of-Scope (Deferred / Future Roadmap):**
  - Multi-passenger linked PNR split-cabin management.
  - Native airline Global Distribution System (GDS) direct connections (relying on Aggregator APIs like Amadeus).

## 3. System Architecture & Component Mapping
- **Frontend Layer:** React SPA, Tailwind CSS, real-time WebSocket client.
- **API Gateway & Routing Layer:** FastAPI (Python 3.11+), Pydantic v2 validation, PII masking middleware.
- **Agent Orchestration Layer:** LangGraph state machine, Redis checkpointer (`AsyncRedisSaver`).
- **Data & Persistence Layer:** PostgreSQL (Supabase) for audit logs/user state + Redis for caching and session state.
- **External Integration Layer:** Amadeus Flight API, Twilio API.

## 4. Risk Analysis & Diagnostic Framework (Failure Modes)
- **Risk 1: LLM Latency or Timeout (>3s).**
  - *Diagnostic:* Monitor execution spans.
  - *Mitigation:* Trigger Dual Fallback Stack to bypass LLM and execute deterministic Python scoring matrix.
- **Risk 2: External Travel API Outage / Rate-Limiting.**
  - *Diagnostic:* HTTP 429 / 5xx errors from Amadeus.
  - *Mitigation:* Fallback to Redis flight cache with a 'Simulated Live Feed' indicator.
- **Risk 3: Concurrency & State Desync Across Channels.**
  - *Diagnostic:* User approves on SMS while laptop dashboard stays active.
  - *Mitigation:* Redis Pub/Sub broadcast of `STATE_UPDATE` event to instantly close pending UI banners.

## 5. Definition of Done (DoD) for Engineering Sprints
- Code is 100% type-hinted using Python typing and Pydantic.
- Zero placeholder comments; fully realized modular architecture.
- Passing unit tests for hard filters and scoring matrix calculations.
- Strict adherence to 'CLAUDE.md' and 'AGI_RULES.md' governance policies.
