"""Collapses the many names one merchant bills under into a single label.

The card statement and the Wallet app show the acquirer's descriptor, not the
brand, so a single iFood order can arrive as `IFD*53.700.820 ELIZABE`,
`IFD Sal Parrilla` or `IFD ESPETIN DE RUA PRI`. Grouping and totals are useless
if all of those count as different merchants.

The original text is never lost — it stays on the transaction's `raw_line`.
"""

import re
import unicodedata

# Matched against an accent-stripped, punctuation-free, lowercased name.
CANONICAL_RULES: list[tuple[re.Pattern, str]] = [
    # iFood's acquirer prefix is "IFD", sometimes with the restaurant appended.
    (re.compile(r"\b(?:ifd|ifood|i food)\b"), "iFood"),
    (re.compile(r"\buber\b"), "Uber"),
    # The ride app 99 bills as "99", "99*", "99pop", "99 Tecnologia".
    (re.compile(r"^99(?:\b|pop|app|taxi|tecnologia)"), "99"),
]


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    ascii_text = decomposed.encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", ascii_text)).strip()


def canonical(merchant: str) -> str:
    """Returns the brand name if we recognise one, otherwise the name unchanged."""
    if not merchant:
        return merchant
    haystack = normalize(merchant)
    for pattern, replacement in CANONICAL_RULES:
        if pattern.search(haystack):
            return replacement
    return merchant.strip()
