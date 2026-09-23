"""Moteur d'extraction EPS / Revenue depuis le texte brut d'un dépôt SEC.

Chemin chaud du Sniper : aucune exception ne doit jamais en sortir — une
valeur non trouvée renvoie `None`, jamais une erreur qui bloquerait la
décision de trading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

_MONEY = r"[-+]?\$?\s?\(?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?"

_EPS_PATTERNS = [
    re.compile(
        r"(?:diluted\s+)?earnings?\s+per\s+(?:diluted\s+)?share[^$\d]{0,40}?(" + _MONEY + r")",
        re.IGNORECASE,
    ),
    re.compile(r"(?:diluted\s+)?EPS[^$\d]{0,40}?(" + _MONEY + r")", re.IGNORECASE),
    re.compile(r"(" + _MONEY + r")\s+per\s+(?:diluted\s+)?share", re.IGNORECASE),
]

_REVENUE_PATTERNS = [
    re.compile(
        r"(?:net\s+)?revenues?\s+(?:of|was|were|totaled|increased to|decreased to)"
        r"[^$\d]{0,40}?(" + _MONEY + r")\s*(million|billion)?",
        re.IGNORECASE,
    ),
    re.compile(r"total\s+revenues?[^$\d]{0,40}?(" + _MONEY + r")\s*(million|billion)?", re.IGNORECASE),
]

_UNIT_MULTIPLIERS = {"million": Decimal("1e6"), "billion": Decimal("1e9")}


@dataclass(frozen=True)
class ExtractionResult:
    eps: Optional[Decimal]
    revenue: Optional[Decimal]
    raw_snippet: str
    confidence: float


def _parse_money(raw: str, unit: Optional[str] = None) -> Optional[Decimal]:
    cleaned = raw.strip().replace("$", "").strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if negative:
        value = -value
    if unit:
        value *= _UNIT_MULTIPLIERS.get(unit.lower(), Decimal("1"))
    return value


def _search_first(patterns: list[re.Pattern], text: str) -> tuple[Optional[Decimal], str]:
    for pattern in patterns:
        match = pattern.search(text)
        if not match:
            continue
        unit = match.group(2) if match.re.groups >= 2 else None
        value = _parse_money(match.group(1), unit)
        if value is None:
            continue
        start, end = max(match.start() - 20, 0), min(match.end() + 20, len(text))
        return value, text[start:end].strip()
    return None, ""


def extract_eps(text: str) -> tuple[Optional[Decimal], str]:
    return _search_first(_EPS_PATTERNS, text)


def extract_revenue(text: str) -> tuple[Optional[Decimal], str]:
    return _search_first(_REVENUE_PATTERNS, text)


def extract_financials(text: str) -> ExtractionResult:
    """Extrait EPS et Revenue depuis le corps d'un 8-K / communiqué de presse.

    `confidence` = proportion des deux champs effectivement trouvés (0, 0.5 ou 1).
    """
    eps, eps_snippet = extract_eps(text)
    revenue, revenue_snippet = extract_revenue(text)

    found = sum(1 for value in (eps, revenue) if value is not None)
    snippet = " | ".join(part for part in (eps_snippet, revenue_snippet) if part)

    return ExtractionResult(eps=eps, revenue=revenue, raw_snippet=snippet, confidence=found / 2)
