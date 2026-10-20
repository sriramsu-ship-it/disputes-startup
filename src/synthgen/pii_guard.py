"""Checks that generated text contains no real-looking SSNs or payment card numbers.

SSN rule (SSA, https://www.ssa.gov/employer/randomizationfaqs.html, retrieved
2026-10-20): area numbers 000, 666 and 900-999 are excluded, and group 00 and
serial 0000 are never assigned. So an SSN-shaped string is "possibly real" unless
its area is 000/666/9xx, or its group is 00, or its serial is 0000. Our synthetic
values use area 9xx AND group 00. Group 00 also falls outside the ITIN group
ranges, so they do not look like ITINs either.

Card rule: any run of 13-19 digits (spaces or hyphens allowed between digits)
that passes the Luhn check is treated as a possibly real card number.
"""
from __future__ import annotations

import re

# Boundaries exclude letters too, so digit runs inside hex hashes or IDs (SYNACCT..., sha256) are skipped.
SSN_SHAPED = re.compile(r"(?<![0-9A-Za-z])(\d{3})[- ]?(\d{2})[- ]?(\d{4})(?![0-9A-Za-z])")
DIGIT_RUN = re.compile(r"(?<![0-9A-Za-z])\d(?:[ -]?\d){12,18}(?![0-9A-Za-z])")


def ssn_possibly_real(area: str, group: str, serial: str) -> bool:
    a = int(area)
    return not (a == 0 or a == 666 or a >= 900 or group == "00" or serial == "0000")


def luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def find_real_looking_pii(text: str) -> list[str]:
    hits = []
    for m in SSN_SHAPED.finditer(text):
        # Only hyphen/space separated or bare 9-digit strings count as SSN-shaped.
        if ssn_possibly_real(*m.groups()):
            hits.append(f"ssn:{m.group(0)}")
    for m in DIGIT_RUN.finditer(text):
        digits = re.sub(r"[ -]", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            hits.append(f"card:{m.group(0)}")
    return hits


def synthetic_ssn(rng) -> str:
    """Area 900-999 and group 00: never assigned by SSA."""
    return f"{rng.randint(900, 999)}-00-{rng.randint(1, 9999):04d}"


def bait_card_number(rng) -> str:
    """16 digits that deliberately FAIL the Luhn check (PII bait only)."""
    while True:
        digits = "".join(str(rng.randint(0, 9)) for _ in range(16))
        if not luhn_ok(digits):
            return " ".join(digits[i:i + 4] for i in range(0, 16, 4))
