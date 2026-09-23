"""Circuit breakers et dimensionnement de position.

Deux circuit breakers distincts, comme spécifié dans le cahier des charges :
- **Liquidité** (Phase 2) : refuse le trade si le spread est trop large ou le
  carnet vide — empêche d'acheter un prix fictif juste après l'annonce.
- **Risque** (Phase 4, Golden Hour) : Stop-Loss / Take-Profit / Trailing Stop
  qui coupent la position si le marché se retourne.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from src.config import RiskConfig


class CircuitBreakerReason(str, Enum):
    SPREAD_TOO_WIDE = "spread_too_wide"
    BOOK_EMPTY = "book_empty"
    NONE = "none"


@dataclass(frozen=True)
class LiquidityCheck:
    passed: bool
    spread_pct: Decimal
    reason: CircuitBreakerReason


def check_liquidity(bid: Decimal, ask: Decimal, book_volume: int, risk_config: RiskConfig) -> LiquidityCheck:
    """Circuit Breaker Liquidité : bid/ask absents, carnet vide ou spread
    excessif (> `max_spread_pct`, 1.5 % par défaut) annulent le trade."""
    if bid <= 0 or ask <= 0 or book_volume <= 0:
        return LiquidityCheck(passed=False, spread_pct=Decimal("0"), reason=CircuitBreakerReason.BOOK_EMPTY)

    mid = (bid + ask) / 2
    spread_pct = ((ask - bid) / mid) * 100

    if book_volume < risk_config.min_book_volume:
        return LiquidityCheck(passed=False, spread_pct=spread_pct, reason=CircuitBreakerReason.BOOK_EMPTY)

    if spread_pct > Decimal(str(risk_config.max_spread_pct)):
        return LiquidityCheck(passed=False, spread_pct=spread_pct, reason=CircuitBreakerReason.SPREAD_TOO_WIDE)

    return LiquidityCheck(passed=True, spread_pct=spread_pct, reason=CircuitBreakerReason.NONE)


def position_size(account_equity: Decimal, entry_price: Decimal, risk_config: RiskConfig) -> int:
    """Nombre d'actions tel que la position ne dépasse jamais le plafond notionnel."""
    if entry_price <= 0:
        return 0
    cap = min(account_equity, Decimal(str(risk_config.max_position_notional_usd)))
    return int(cap // entry_price)


@dataclass(frozen=True)
class TrailingStopState:
    entry_price: Decimal
    high_water_mark: Decimal
    stop_price: Decimal


def init_trailing_stop(entry_price: Decimal, risk_config: RiskConfig) -> TrailingStopState:
    trailing_pct = Decimal(str(risk_config.trailing_stop_pct)) / 100
    return TrailingStopState(
        entry_price=entry_price,
        high_water_mark=entry_price,
        stop_price=entry_price * (1 - trailing_pct),
    )


def update_trailing_stop(state: TrailingStopState, last_price: Decimal, risk_config: RiskConfig) -> TrailingStopState:
    """Relève le stop uniquement quand un nouveau plus-haut est atteint (trailing)."""
    if last_price <= state.high_water_mark:
        return state
    trailing_pct = Decimal(str(risk_config.trailing_stop_pct)) / 100
    new_stop = last_price * (1 - trailing_pct)
    return TrailingStopState(
        entry_price=state.entry_price,
        high_water_mark=last_price,
        stop_price=max(state.stop_price, new_stop),
    )


def should_exit_position(state: TrailingStopState, last_price: Decimal, risk_config: RiskConfig) -> Optional[str]:
    """Renvoie 'stop_loss', 'take_profit', 'trailing_stop', ou None."""
    hard_stop = state.entry_price * (1 - Decimal(str(risk_config.stop_loss_pct)) / 100)
    take_profit = state.entry_price * (1 + Decimal(str(risk_config.take_profit_pct)) / 100)

    if last_price <= hard_stop:
        return "stop_loss"
    if last_price >= take_profit:
        return "take_profit"
    if last_price <= state.stop_price:
        return "trailing_stop"
    return None
