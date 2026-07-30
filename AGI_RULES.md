# Antigravity CLI Execution Rules & System Directives

## 1. Pre-Execution Scan Mandate
- Before generating, modifying, or deleting any file, the CLI must scan this document and the root 'CLAUDE.md' file. All directives herein override default behaviors.

## 2. Code Quality & Architecture Enforcement
- **Stack:** Python 3.11+, FastAPI, Pydantic v2, LangGraph, Redis, PostgreSQL.
- **Completeness:** Zero placeholder comments (e.g., no `# add implementation here`). Write complete, production-grade, type-hinted code.
- **Resilience:** Implement the Dual Fallback Stack for all external APIs and LLM calls (auto-fallback to Python deterministic scripts and Redis cache on timeout/failure).

## 3. Financial Security & Compliance
- **PII Masking:** Every payload entering the LLM or logging pipeline must pass through a strict sanitization/masking layer. Never store or log plain-text credit card numbers or passport data.
- **XAI Audit Logging:** Every agent decision (e.g., flight selection scoring, hard filter drops) must output a structured JSON explanation audit log.

## 4. Documentation & Maintenance
- Every new module must include clean docstrings explaining the business logic and weight matrices (e.g., Price Delta 40%, Travel Time 25%, Alliance 20%, Layovers 15%).
- Ensure all dependencies are correctly added to 'requirements.txt' with explicit version locking.
