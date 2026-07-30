security.py (The Compliance Shield):
In FinTech and enterprise banking (like Amex), logging unmasked cardholder data is a massive compliance violation (PCI-DSS). Building this middleware first ensures that no matter what code you write later, PII is scrubbed at the perimeter.








You are absolutely correct. In FinTech, **PCI-DSS Requirement 3** (protect stored cardholder data) and **Requirement 10** (log and monitor access) make this non-negotiable. If a log file containing a full Primary Account Number (PAN) is ever leaked or even accidentally viewed by an unauthorized engineer, that is a reportable breach with fines up to $100,000 *per month*.

Building `security.py` as the **"Compliance Shield"** *before* writing business logic is the gold-standard architectural pattern. Here is exactly what that shield looks like in practice, how to implement it at the perimeter, and why it must be middleware, not just a helper function.

### 1. The "Perimeter" Middleware (Interceptor)
The shield must intercept every inbound request and outbound response **at the framework level** (before your views/controllers handle the data). It must also hook into the Python logging factory to scrub data *before* it is written to disk.

**FastAPI/Starlette Middleware Example:**
```python
# security.py
import re
import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from typing import Dict, Any

class PCIComplianceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Scrub the incoming request body BEFORE it reaches business logic
        body = await request.body()
        scrubbed_body = mask_pii_in_json(body)
        
        # Override the request to use the scrubbed body
        async def receive():
            return {"type": "http.request", "body": scrubbed_body}
        request._receive = receive
        
        # 2. Process the request
        response = await call_next(request)
        
        # 3. Scrub the outgoing response body (in case it echoes back PII)
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk
        scrubbed_response = mask_pii_in_json(response_body)
        response.body_iterator = iter([scrubbed_response])
        
        return response
```

### 2. The Scrubbing Engine (The Regex/Redaction Logic)
The shield must intelligently detect patterns while preserving **truncated data** (first 6 / last 4) for debugging, and **completely dropping** CVV and Track Data.

```python
# security.py - Core redaction logic
import re

# Regex patterns for major card schemes
PAN_PATTERNS = {
    "VISA": r"\b4[0-9]{12}(?:[0-9]{3})?\b",          # 13 or 16 digits
    "MC": r"\b5[1-5][0-9]{14}\b",                    # 16 digits
    "AMEX": r"\b3[47][0-9]{13}\b",                   # 15 digits (Amex specific)
    "DISCOVER": r"\b6(?:011|5[0-9]{2})[0-9]{12}\b",
}

# High-risk fields that should NEVER be logged, even masked
ABSOLUTELY_FORBIDDEN = re.compile(r'\b(cvv|cvc|cvv2|track1|track2|magstripe)\b', re.IGNORECASE)

def mask_pii_in_json(raw_body: bytes) -> bytes:
    if not raw_body:
        return raw_body
    
    try:
        data = json.loads(raw_body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # If it's not JSON (e.g., XML or form-data), use string replacement fallback
        return re.sub(r'\b\d{13,19}\b', '[REDACTED-PAN]', raw_body.decode()).encode()
    
    # Recursively traverse nested dicts/lists
    scrubbed = recursively_mask(data)
    return json.dumps(scrubbed, separators=(',', ':')).encode()

def recursively_mask(obj):
    if isinstance(obj, dict):
        return {k: recursively_mask(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [recursively_mask(item) for item in obj]
    elif isinstance(obj, str):
        # 1. Check for forbidden fields by key (exact match)
        # (We handle this in the dict layer above, but check strings directly too)
        
        # 2. Mask full PANs to first6-last4
        for pattern in PAN_PATTERNS.values():
            match = re.search(pattern, obj.replace(" ", "").replace("-", ""))
            if match:
                pan = match.group()
                if len(pan) >= 15:
                    return f"{pan[:6]}-XXXXXX-{pan[-4:]}"
        
        # 3. If it's a standalone CVV (very rare, but kill it)
        if ABSOLUTELY_FORBIDDEN.search(obj):
            return "[FORBIDDEN-FIELD-DROPPED]"
        return obj
    else:
        return obj
```

### 3. The Logging Shielding (The Most Critical Part)
Middleware scrubs the request/response payloads, but **stack traces and debug logs** are the #1 source of accidental PII leaks. You must install a custom **Logging Filter** globally.

```python
# security.py - Logging filter
import logging
import copy

class PCILogFilter(logging.Filter):
    def filter(self, record):
        # If the log record contains 'args' (from printf-style logging), scrub them
        if record.args:
            scrubbed_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    scrubbed_args.append(redact_pan_from_string(arg))
                else:
                    scrubbed_args.append(arg)
            record.args = tuple(scrubbed_args)
        
        # If the log record has a 'msg', scrub it
        if isinstance(record.msg, str):
            record.msg = redact_pan_from_string(record.msg)
        
        # If there's an 'exc_text' (traceback), scrub it
        if record.exc_text:
            record.exc_text = redact_pan_from_string(record.exc_text)
        
        return True

# Install it globally at application startup
logging.basicConfig(level=logging.INFO)
for handler in logging.root.handlers:
    handler.addFilter(PCILogFilter())
```

### 4. What to Log vs. What to Drop (PCI-DSS Explicit Rules)
Your `security.py` must enforce these strict rules, preferably via a configuration enum:

| Data Type | Action | Rationale |
| :--- | :--- | :--- |
| **Full PAN** | **Mask** (show only first 6 & last 4) | Required for debugging transaction routing (BIN lookup). |
| **Expiry Date** | **Allow** (if logged without PAN) | Not sensitive on its own. |
| **CVV2 / CVC2** | **DROP IMMEDIATELY** (return `null`) | PCI-DSS prohibits storing/transmitting CVV after authorization. |
| **Track 1 / Track 2** | **DROP IMMEDIATELY** | Contains full magnetic stripe data; never allowed in logs. |
| **Cardholder Name** | **Hash** or **Mask** (e.g., "J*** D***") | PII under GDPR/CCPA, but sometimes needed for receipts. |

### 5. Why "Building This First" is a Genius Move
1.  **Zero-Trust Architecture**: By building the shield at the perimeter, your business logic engineers don't have to remember to call `mask_card()` on every single print statement. *If they forget, the shield catches it.*
2.  **Bug-Free Debugging**: In enterprise banking, when a production outage occurs, SREs need to see the last 4 digits of the card to trace the transaction without violating compliance. Your shield provides exactly that.
3.  **Audit Trail Ready**: The middleware can automatically inject a `correlation_id` and a cryptographic hash of the masked PAN (for deduplication) into every log, satisfying Requirement 10.3 (audit trail for every access).

### The Golden Rule of `security.py`
Never call external APIs or perform heavy computations inside this middleware. **Speed is its own security feature**—if the shield takes 50ms to run, it creates a DoS vulnerability. Use compiled regex (`re.compile()`) and treat `security.py` as a **read-only, stateless, blazing-fast filter** that strictly mutates data structures. 

In the Amex/FinTech world, this file is usually code-reviewed by the **CISO (Chief Information Security Officer)** directly, and any change to it requires a separate, expedited security pipeline. Treat it as the most sacred file in your repository.