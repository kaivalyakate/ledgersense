import re

REJECTION_MESSAGE = "If you try to ask something nasty, your manager will be fired."

# Rule 2: prompt injection patterns
_INJECTION = re.compile(
    r"ignore\s+(all\s+)?(previous|prior)\s+(instructions?|prompts?|context)"
    r"|forget\s+(your\s+)?(instructions?|rules?|context|previous)"
    r"|you\s+are\s+now\s+(a\b|an\b|the\b)"
    r"|act\s+as\s+(a\b|an\b|if\b)"
    r"|pretend\s+(you\s+are|to\s+be)"
    r"|new\s+persona"
    r"|system\s+prompt"
    r"|\bjailbreak\b"
    r"|\bDAN\b"
    r"|override\s+(your\s+)?(instructions?|rules?)"
    r"|bypass\s+(the\s+)?(filter|guardrail|restriction)",
    re.IGNORECASE,
)

# Rule 3: financial topic whitelist — at least one must match
_FINANCIAL_KEYWORDS = re.compile(
    r"\b(transaction|spend|spending|spent|revenue|income|expense|expenses"
    r"|vendor|vendors|category|categories|amount|invoice|payment|payments"
    r"|cost|costs|profit|loss|financial|finance|account|accounts|budget"
    r"|cash|purchase|purchases|entity|entities|monthly|weekly|daily"
    r"|total|sum|average|count|largest|smallest|highest|lowest"
    r"|compare|trend|categorize|categorization|bakery|restaurant"
    r"|construction|ledger|money|dollar|paid|charge|bill|receipt"
    r"|refund|deposit|withdrawal|payroll|salary|pending|approved|review)\b",
    re.IGNORECASE,
)
_FINANCIAL_PHRASES = re.compile(r"how\s+much|how\s+many", re.IGNORECASE)

# Rule 4: nastiness blocklist
_NASTY = re.compile(
    r"\b(hack|exploit|attack|malware|phishing|steal|fraud|launder"
    r"|sex|porn|nude|naked|drug|cocaine|meth|murder|kill|bomb|weapon)\b",
    re.IGNORECASE,
)


def check_question(question: str) -> tuple[bool, str]:
    """
    Returns (is_allowed, reason_code).
    Callers should show REJECTION_MESSAGE when is_allowed is False;
    reason_code is for internal logging only, never expose it in API responses.
    """
    q = question.strip()

    if not q:
        return False, "empty"

    if len(q) > 500:
        return False, "too_long"

    if _INJECTION.search(q):
        return False, "prompt_injection"

    if _NASTY.search(q):
        return False, "nasty"

    if not _FINANCIAL_KEYWORDS.search(q) and not _FINANCIAL_PHRASES.search(q):
        return False, "off_topic"

    return True, "ok"
