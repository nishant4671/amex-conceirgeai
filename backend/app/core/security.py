import re
from typing import Any, Dict, List, Union

# Regex patterns for common PII
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d[ -]*?){13,16}\b")
# Standard Passport format: alphanumeric, length 6-9
PASSPORT_REGEX = re.compile(r"\b[A-PR-WYa-pr-wy][1-9]\d\s?\d{4}[1-9]\b|\b[A-Z0-9]{6,9}\b", re.IGNORECASE)
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Sensitive dictionary keys that should be masked directly
SENSITIVE_KEYS = {
    "cvv",
    "cvc",
    "password",
    "secret",
    "token",
    "credit_card",
    "passport",
    "email",
    "name",
    "first_name",
    "last_name",
    "phone",
    "phone_number",
    "ssn",
    "card_number",
}


def mask_string(text: str) -> str:
    """Mask sensitive patterns (emails, credit cards, passport numbers) in raw text."""
    if not text:
        return text

    # Mask credit cards
    text = CREDIT_CARD_REGEX.sub("[MASKED_CARD]", text)

    # Mask emails
    text = EMAIL_REGEX.sub("[MASKED_EMAIL]", text)

    # Mask passport patterns: basic check to avoid over-masking generic short strings
    # We will match if it's explicitly identified as a likely passport format
    def passport_replacer(match: re.Match) -> str:
        val = match.group(0)
        # Avoid masking normal words/short numbers unless they look like passport numbers
        if len(val) >= 7 and any(c.isdigit() for c in val) and any(c.isalpha() for c in val):
            return "[MASKED_PASSPORT]"
        return val

    text = PASSPORT_REGEX.sub(passport_replacer, text)
    return text


def mask_payload(payload: Any) -> Any:
    """Recursively traverse a payload (dict, list, or primitive) and mask PII fields."""
    if isinstance(payload, dict):
        masked_dict: Dict[str, Any] = {}
        for k, v in payload.items():
            key_lower = k.lower()
            if key_lower in SENSITIVE_KEYS:
                if isinstance(v, str):
                    if key_lower in ("email", "billing_email"):
                        masked_dict[k] = "[MASKED_EMAIL]"
                    elif key_lower in ("card_number", "credit_card"):
                        masked_dict[k] = "[MASKED_CARD]"
                    elif key_lower in ("passport", "passport_number", "passport_id"):
                        masked_dict[k] = "[MASKED_PASSPORT]"
                    elif key_lower in ("name", "first_name", "last_name"):
                        masked_dict[k] = "[MASKED_NAME]"
                    elif key_lower in ("phone", "phone_number"):
                        masked_dict[k] = "[MASKED_PHONE]"
                    else:
                        masked_dict[k] = "[MASKED]"
                else:
                    masked_dict[k] = "[MASKED]"
            else:
                masked_dict[k] = mask_payload(v)
        return masked_dict
    elif isinstance(payload, list):
        return [mask_payload(item) for item in payload]
    elif isinstance(payload, str):
        return mask_string(payload)
    else:
        return payload
