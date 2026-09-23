"""Comparaison réel (Regex) vs consensus analystes : décide s'il y a un
signal de trading exploitable, avant même de vérifier la liquidité.

Sans cette étape, le Sniper achèterait sur n'importe quel 8-K, y compris un
earnings miss ou une extraction Regex ratée — ce module comble ce manque.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from src.config import RiskConfig
from src.core.nlp_regex import ExtractionResult


class SignalReason(str, Enum):
    EPS_BEAT = "eps_beat"
    EPS_MISS_OR_INLINE = "eps_miss_or_inline"
    MISSING_EPS = "missing_eps"
    NO_CONSENSUS = "no_consensus"
    LOW_REGEX_CONFIDENCE = "low_regex_confidence"


@dataclass(frozen=True)
class EarningsSignal:
    side: Optional[str]  # "buy" si le signal est exploitable, sinon None
    eps_surprise_pct: Optional[Decimal]
    revenue_surprise_pct: Optional[Decimal]
    reason: SignalReason

    @property
    def tradeable(self) -> bool:
        return self.side is not None


def _surprise_pct(actual: Optional[Decimal], consensus: Optional[Decimal]) -> Optional[Decimal]:
    if actual is None or consensus is None or consensus == 0:
        return None
    return ((actual - consensus) / abs(consensus)) * 100


def evaluate_earnings_surprise(
    extraction: ExtractionResult,
    consensus_eps: Optional[Decimal],
    consensus_revenue: Optional[Decimal],
    risk_config: RiskConfig,
) -> EarningsSignal:
    """Compare l'EPS/Revenue extraits par Regex au consensus analystes.

    N'autorise un signal `buy` que si :
    - la Regex a trouvé au moins l'EPS, avec une confiance suffisante
      (`MIN_REGEX_CONFIDENCE`) ;
    - un consensus EPS existe pour ce symbole (chargé en Pre-Market depuis
      `sniper.assets`) ;
    - le beat dépasse `MIN_EPS_SURPRISE_PCT` (0 % par défaut : tout beat
      compte, tout miss ou résultat en ligne est ignoré).

    Ne gère que l'achat (pas de vente à découvert sur un miss) : c'est une
    limite volontaire, le projet n'a pas d'infrastructure de short pour
    l'instant.
    """
    revenue_surprise = _surprise_pct(extraction.revenue, consensus_revenue)

    if extraction.eps is None:
        return EarningsSignal(None, None, revenue_surprise, SignalReason.MISSING_EPS)

    if consensus_eps is None:
        return EarningsSignal(None, None, revenue_surprise, SignalReason.NO_CONSENSUS)

    if extraction.confidence < risk_config.min_regex_confidence:
        eps_surprise = _surprise_pct(extraction.eps, consensus_eps)
        return EarningsSignal(None, eps_surprise, revenue_surprise, SignalReason.LOW_REGEX_CONFIDENCE)

    eps_surprise = _surprise_pct(extraction.eps, consensus_eps)
    if eps_surprise is not None and eps_surprise > Decimal(str(risk_config.min_eps_surprise_pct)):
        return EarningsSignal("buy", eps_surprise, revenue_surprise, SignalReason.EPS_BEAT)

    return EarningsSignal(None, eps_surprise, revenue_surprise, SignalReason.EPS_MISS_OR_INLINE)
